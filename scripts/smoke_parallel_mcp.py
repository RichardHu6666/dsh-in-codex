"""Validate two MCP clients and a shared global task limit.

Use --live to opt into billable Harness tasks.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness_mcp.config import load_local_credentials
from evidence import harness_test_evidence

ROOT = Path(__file__).resolve().parents[1]


def unpack(result):
    if result.isError:
        raise RuntimeError(str(result.content))
    return result.structuredContent or json.loads(result.content[0].text)


async def open_client(stack: AsyncExitStack, env: dict[str, str]) -> ClientSession:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "harness_mcp.server"], env=env,
    )
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


async def wait_task(session: ClientSession, task_id: str) -> dict:
    cursor = 0
    async with asyncio.timeout(900):
        while True:
            task = unpack(await session.call_tool("wait_task", {
                "task_id": task_id, "cursor": cursor, "limit": 100, "timeout_sec": 10,
            }))
            cursor = task["next_cursor"]
            if task["status"] not in {"queued", "running", "cancelling"}:
                return task
            while task["has_more"]:
                task = unpack(await session.call_tool("get_task", {
                    "task_id": task_id, "cursor": cursor, "limit": 100,
                }))
                cursor = task["next_cursor"]


def verify(workspace: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-v"], cwd=workspace,
        capture_output=True, text=True, timeout=30,
    )
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


async def main(live: bool, count: int):
    if not live:
        raise SystemExit("This is a billable test. Re-run explicitly with --live.")
    if not 2 <= count <= 16:
        raise SystemExit("--count must be between 2 and 16")
    load_local_credentials(ROOT)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY missing; set it locally, never in chat.")

    test_root = ROOT / "work" / f"parallel-check-{uuid.uuid4().hex[:12]}"
    test_root.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        HARNESS_MCP_ROOT=str(test_root),
        HARNESS_MCP_NODE_ROOT=str(ROOT),
        HARNESS_MCP_TIMEOUT="600",
        HARNESS_MCP_MAX_CONCURRENCY=str(count),
    )
    if os.name == "nt":
        command = (
            f"& '{sys.executable}' -m unittest discover -v; "
            '$code = $LASTEXITCODE; Write-Output "HARNESS_TEST_EXIT=$code"; exit $code'
        )
    else:
        command = (
            f"{shlex.quote(sys.executable)} -m unittest discover -v; "
            'code=$?; echo "HARNESS_TEST_EXIT=$code"; exit "$code"'
        )
    report = {"count": count, "root": str(test_root), "passed": False}
    try:
        async with AsyncExitStack() as stack:
            clients = [
                await open_client(stack, env),
                await open_client(stack, env),
            ]
            expected = {
                "submit_task", "get_task", "wait_task", "continue_task", "cancel_task",
            }
            for client in clients:
                assert {tool.name for tool in (await client.list_tools()).tools} == expected

            submitted = []
            for index in range(count):
                workspace = test_root / "work" / f"task-{index + 1}"
                shutil.copytree(ROOT / "examples" / "smoke_project", workspace)
                client = clients[index % 2]
                task = unpack(await client.call_tool("submit_task", {
                    "workspace": str(workspace),
                    "instruction": (
                        f"Parallel acceptance task {index + 1}: fix arithmetic.add, preserve "
                        f"existing tests, add a zero test, and run exactly:\n{command}"
                    ),
                    "acceptance": [
                        "add passes positive, negative and zero tests",
                        "unittest exits zero with HARNESS_TEST_EXIT=0",
                    ],
                }))
                submitted.append({
                    "task": task, "workspace": workspace, "client": index % 2,
                })

            completed = await asyncio.gather(*(
                wait_task(clients[item["client"]], item["task"]["task_id"])
                for item in submitted
            ))
            report["tasks"] = []
            for item, task in zip(submitted, completed, strict=True):
                log = test_root / ".runtime" / "tasks" / f"{task['task_id']}.jsonl"
                records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
                evidence = harness_test_evidence(records, 1, task["session_id"])
                independent = verify(item["workspace"])
                assert task["status"] == "completed"
                assert evidence
                assert independent["exit_code"] == 0
                other = clients[1 - item["client"]]
                cross_read = unpack(await other.call_tool(
                    "get_task", {"task_id": task["task_id"], "limit": 1},
                ))
                assert cross_read["session_id"] == task["session_id"]
                report["tasks"].append({
                    "task_id": task["task_id"], "session_id": task["session_id"],
                    "harness_tests": evidence, "independent": independent,
                })

            first = submitted[0]
            first_task = completed[0]
            other = clients[1 - first["client"]]
            continued = unpack(await other.call_tool("continue_task", {
                "task_id": first_task["task_id"],
                "feedback": (
                    "Add multiply(a, b), add positive and negative multiplication tests, "
                    f"then run exactly:\n{command}"
                ),
            }))
            assert continued["session_id"] == first_task["session_id"]
            second = await wait_task(other, first_task["task_id"])
            log = test_root / ".runtime" / "tasks" / f"{first_task['task_id']}.jsonl"
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            assert harness_test_evidence(records, 2, first_task["session_id"])
            assert verify(first["workspace"])["exit_code"] == 0
            report["continued"] = {
                "task_id": second["task_id"], "session_id": second["session_id"],
                "round": second["round"], "status": second["status"],
            }

            cancelled = []
            for index, item in enumerate(submitted):
                other = clients[1 - item["client"]]
                state = unpack(await other.call_tool(
                    "cancel_task", {"task_id": item["task"]["task_id"]},
                ))
                assert state["stopped_confirmed"] is True
                cancelled.append(state["task_id"])
            report["cancelled"] = cancelled
            report["passed"] = True
    finally:
        path = test_root / ".runtime" / "parallel-live-smoke.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(path), "passed": report["passed"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--count", type=int, default=8)
    arguments = parser.parse_args()
    asyncio.run(main(arguments.live, arguments.count))
