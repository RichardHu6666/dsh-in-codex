"""MCP discovery by default; --live opts into two billable Harness coding turns."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness_mcp.config import load_local_credentials
from harness_mcp.evidence import harness_test_evidence

ROOT = Path(__file__).resolve().parents[1]


def unpack(result):
    if result.isError:
        raise RuntimeError(str(result.content))
    return result.structuredContent or json.loads(result.content[0].text)


async def wait_task(session, task_id):
    cursor = 0
    try:
        async with asyncio.timeout(600):
            while True:
                task = unpack(await session.call_tool(
                    "wait_task", {
                        "task_id": task_id, "cursor": cursor, "limit": 100,
                        "timeout_sec": 10,
                    },
                ))
                cursor = task["next_cursor"]
                if task["status"] not in {"queued", "running", "cancelling"}:
                    if task["status"] != "completed":
                        raise RuntimeError(f"Harness task ended: {task['status']}: {task['error']}")
                    return task
                await asyncio.sleep(2)
    except BaseException:
        await session.call_tool("cancel_task", {"task_id": task_id})
        raise


def verify(workspace):
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-v"], cwd=workspace,
        capture_output=True, text=True, timeout=30,
    )
    return {"command": [sys.executable, "-m", "unittest", "discover", "-v"],
            "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


async def main(live: bool, isolated: bool = False):
    load_local_credentials(ROOT)
    if live and not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY missing. Set it locally; do not paste it in chat.")
    env = os.environ.copy()
    test_root = ROOT / "work" / f"bridge-check-{uuid.uuid4().hex[:12]}" if isolated else ROOT
    test_root.mkdir(parents=True, exist_ok=True)
    env["HARNESS_MCP_ROOT"] = str(test_root)
    env["HARNESS_MCP_NODE_ROOT"] = str(ROOT)
    env["HARNESS_MCP_TIMEOUT"] = "600"
    report = {"mode": "live" if live else "discovery", "model_called": False}
    if os.name == "nt":
        test_command = (
            f"& '{sys.executable}' -m unittest discover -v; "
            '$code = $LASTEXITCODE; Write-Output "HARNESS_TEST_EXIT=$code"; exit $code'
        )
    else:
        import shlex
        test_command = (
            f'{shlex.quote(sys.executable)} -m unittest discover -v; '
            'code=$?; echo "HARNESS_TEST_EXIT=$code"; exit "$code"'
        )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "harness_mcp.server"], env=env,
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                report["tools"] = sorted(t.name for t in (await session.list_tools()).tools)
                assert report["tools"] == [
                    "cancel_task", "continue_task", "get_task", "submit_task", "wait_task",
                ]
                if live:
                    workspace = test_root / "work" / f"live-smoke-{uuid.uuid4().hex[:12]}"
                    shutil.copytree(ROOT / "examples" / "smoke_project", workspace)
                    report["workspace"] = str(workspace)
                    report["baseline"] = verify(workspace)
                    assert report["baseline"]["exit_code"] != 0
                    first = unpack(await session.call_tool("submit_task", {
                        "workspace": str(workspace),
                        "instruction": (
                            "Fix arithmetic.add. Preserve the existing tests, add a zero case, "
                            "Run the following exact foreground shell command (not a background "
                            f"job) in the task workspace, preserving exit status:\n{test_command}"
                        ),
                        "acceptance": [
                            "add computes sums for positive, negative and zero values",
                            "Existing tests remain intact and unittest discovery exits zero",
                        ],
                    }))
                    report["model_called"] = True
                    report["task_id"] = first["task_id"]
                    report["first"] = await wait_task(session, first["task_id"])
                    log = test_root / ".runtime" / "tasks" / f"{first['task_id']}.jsonl"
                    records = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
                    report["first_harness_tests"] = harness_test_evidence(
                        records, 1, first["session_id"],
                    )
                    report["first_verification"] = verify(workspace)
                    assert report["first_verification"]["exit_code"] == 0
                    assert report["first_harness_tests"], (
                        "Harness did not successfully execute unittest; independent pass is insufficient"
                    )
                    unpack(await session.call_tool("continue_task", {
                        "task_id": first["task_id"],
                        "feedback": (
                            "Preserve the fix. Add multiply(a, b), add positive and negative "
                            "multiplication tests. Run this exact foreground command in the "
                            f"task workspace:\n{test_command}"
                        ),
                    }))
                    report["second"] = await wait_task(session, first["task_id"])
                    records = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
                    report["second_harness_tests"] = harness_test_evidence(
                        records, 2, first["session_id"],
                    )
                    report["second_verification"] = verify(workspace)
                    independent = subprocess.run(
                        [sys.executable, "-c",
                         "from arithmetic import add,multiply; "
                         "assert add(2,3)==5; assert add(-2,0)==-2; "
                         "assert multiply(3,-4)==-12; assert multiply(0,9)==0"],
                        cwd=workspace, capture_output=True, text=True, timeout=30,
                    )
                    report["independent_check"] = {
                        "exit_code": independent.returncode, "stderr": independent.stderr,
                    }
                    assert report["second_verification"]["exit_code"] == 0
                    assert independent.returncode == 0
                    assert report["second_harness_tests"], "Second round lacks Harness test evidence"
                    assert report["first"]["session_id"] == report["second"]["session_id"]
                    report["cancel_idle"] = unpack(await session.call_tool(
                        "cancel_task", {"task_id": first["task_id"]},
                    ))
                report["passed"] = True
    finally:
        path = test_root / ".runtime" / ("live-smoke.json" if live else "mcp-discovery.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(path), "passed": report.get("passed", False),
                          "model_called": report["model_called"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--isolated", action="store_true",
                        help="Use a new state/workspace under work without taking the main MCP lock")
    args = parser.parse_args()
    asyncio.run(main(args.live, args.isolated))
