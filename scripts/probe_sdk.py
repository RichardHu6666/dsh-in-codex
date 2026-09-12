"""Start and initialize the real sdk profile without submitting a model prompt."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import uuid

from harness_mcp.config import Settings
from harness_mcp.processes import SlotLease
from harness_mcp.runner import HarnessRunner
from harness_mcp.store import Task


async def main():
    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault("HARNESS_MCP_ROOT", str(root))
    runner = HarnessRunner(Settings.from_env())
    tid = uuid.uuid4().hex
    task = Task(
        tid,
        ".",
        "SDK initialization probe; no prompt",
        [],
        f"probe-{tid}",
        runner.settings.model,
        status="running",
        owner_pid=runner.owner_pid,
        owner_created=runner.owner_created,
        owner_id=runner.owner_id,
    )
    runner.store.save(task)
    slot = SlotLease(runner.settings.slots / "probe.lock")
    try:
        worker = await runner._spawn(task, slot)
        async with asyncio.timeout(90):
            result = await runner._read(worker)
        task.status = "completed" if result["kind"] == "ready" else "failed"
        task.error = result.get("error")
        runner.store.save(task)
        print(runner.store.redact(json.dumps({
            "probe": "real_sdk_initialize", "model_prompt_sent": False,
            "result": result, "task_id": tid,
        }, indent=2)))
        return 0 if result["kind"] == "ready" else 1
    except Exception as exc:
        task.status = "failed"
        task.error = str(exc)
        runner.store.save(task)
        print(runner.store.redact(json.dumps({
            "error_type": type(exc).__name__,
            "error": str(exc),
        })))
        return 1
    finally:
        await runner._close_worker(tid, force=True)
        slot.close()
        await runner.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
