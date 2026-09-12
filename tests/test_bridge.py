import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import psutil
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness_mcp.config import Settings
from harness_mcp.processes import process_identity
from harness_mcp.runner import HarnessRunner
from harness_mcp.store import Task, TaskStore

FAKE = Path(__file__).with_name("fake_worker.py")


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path, timeout=10)


@pytest.fixture
async def runner(settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-secret-only-for-offline-tests")
    bridge = HarnessRunner(settings, [sys.executable, str(FAKE)])
    try:
        yield bridge
    finally:
        await bridge.close()


async def finished(bridge):
    assert bridge.jobs
    await asyncio.wait_for(asyncio.gather(*(
        asyncio.shield(job) for job in bridge.jobs.values()
    )), 15)


async def test_roundtrip_edit_and_continue(runner):
    result = await runner.submit(".", "FAKE_EDIT", ["record output"])
    tid = result["task_id"]
    assert result["status"] == "queued"
    await finished(runner)
    first = runner.store.view(tid)
    assert first["status"] == "completed"
    assert first["verification"] == "not_independently_verified"
    detail = json.loads(first["final_response"])
    assert detail["round_seen"] == 1
    assert Path(detail["workspace"]) == runner.settings.root
    assert Path(detail["dsh_home"]).is_relative_to(runner.settings.runtime)
    assert detail["secret_echo"] == "[REDACTED]"
    await runner.continue_task(tid, "second round")
    await finished(runner)
    second = runner.store.view(tid)
    assert second["session_id"] == first["session_id"]
    assert second["round"] == 2
    assert json.loads(second["final_response"])["pid"] == detail["pid"]
    assert (runner.settings.root / "generated.txt").read_text() == "2"
    await runner.close()
    reopened = TaskStore(runner.settings)
    assert reopened.get(tid).round == 2


async def test_immediate_cancel(runner):
    result = await runner.submit(".", "FAKE_HANG", ["stop"])
    state = await runner.cancel(result["task_id"])
    assert state["status"] == "cancelled"
    assert state["stopped_confirmed"] is True
    assert all(job.done() for job in runner.jobs.values())


async def test_parallel_tasks_and_workspace_warning(runner):
    first = await runner.submit(".", "FAKE_HANG", ["stop"])
    second = await runner.submit(".", "FAKE_HANG", ["stop"])
    assert second["status"] == "queued"
    assert first["task_id"] in second["warnings"][0]
    with pytest.raises(ValueError, match="not safely stopped"):
        await runner.continue_task(first["task_id"], "x")
    await asyncio.gather(
        runner.cancel(first["task_id"]),
        runner.cancel(second["task_id"]),
    )


async def test_cancel_process_tree(runner):
    result = await runner.submit(".", "FAKE_HANG", ["stop"])
    child = None
    for _ in range(100):
        events = runner.store.view(result["task_id"])["events"]
        child = next((e["data"].get("child_pid") for e in events
                      if e["kind"] == "harness"), None)
        if child:
            break
        await asyncio.sleep(0.05)
    assert child and psutil.pid_exists(child)
    response = await runner.cancel(result["task_id"])
    assert response["stopped_confirmed"] is True
    assert not psutil.pid_exists(child)


@pytest.mark.parametrize("prompt", ["FAKE_ERROR", "FAKE_EOF"])
async def test_worker_errors(runner, prompt):
    result = await runner.submit(".", prompt, ["x"])
    await finished(runner)
    state = runner.store.view(result["task_id"])
    assert state["status"] == "failed"
    assert state["error"]
    assert state["stopped_confirmed"] is True


async def test_timeout(settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    bridge = HarnessRunner(Settings(settings.root, timeout=0.3),
                           [sys.executable, str(FAKE)])
    try:
        result = await bridge.submit(".", "FAKE_HANG", ["x"])
        await finished(bridge)
        assert bridge.store.get(result["task_id"]).status == "timed_out"
        assert bridge.store.get(result["task_id"]).stopped_confirmed is True
    finally:
        await bridge.close()


async def test_no_key(runner, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        await runner.submit(".", "x", ["x"])


async def test_path_constraints(runner):
    with pytest.raises(ValueError, match="within"):
        await runner.submit(str(runner.settings.root.parent), "x", ["x"])
    with pytest.raises(ValueError, match="internal"):
        await runner.submit(".runtime", "x", ["x"])
    with pytest.raises(ValueError, match="acceptance"):
        await runner.submit(".", "x", [])


def test_invalid_task_ids(settings):
    store = TaskStore(settings)
    for value in ["../secret", "../../x", "foo", "a" * 33]:
        with pytest.raises(ValueError, match="invalid"):
            store.get(value)


async def test_multiple_runners_share_runtime(runner):
    second = HarnessRunner(runner.settings, [sys.executable, str(FAKE)])
    try:
        assert second.store.directory == runner.store.directory
    finally:
        await second.close()


async def test_recovery(settings):
    store = TaskStore(settings)
    tid = uuid.uuid4().hex
    store.save(Task(tid, ".", "x", ["x"], tid, "test", status="running"))
    bridge = HarnessRunner(settings)
    try:
        assert bridge.store.get(tid).status == "interrupted"
    finally:
        await bridge.close()


async def test_pagination(runner):
    result = await runner.submit(".", "x", ["x"])
    await finished(runner)
    first = runner.store.view(result["task_id"], limit=1)
    assert first["has_more"]
    second = runner.store.view(result["task_id"], cursor=first["next_cursor"], limit=1)
    assert second["events"][0] != first["events"][0]
    with pytest.raises(ValueError, match="next_cursor"):
        runner.store.view(result["task_id"], cursor=1)


async def test_mcp_stdio_discovery_and_errors(settings):
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    env["HARNESS_MCP_ROOT"] = str(settings.root)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "harness_mcp.server"], env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert {t.name for t in tools} == {
                "submit_task", "get_task", "wait_task", "continue_task", "cancel_task",
            }
            for tool in tools:
                assert "ctx" not in tool.inputSchema.get("properties", {})
            query = next(t for t in tools if t.name == "get_task")
            assert query.annotations.readOnlyHint is True
            assert query.annotations.openWorldHint is False
            wait = next(t for t in tools if t.name == "wait_task")
            assert wait.annotations.readOnlyHint is True
            assert wait.annotations.openWorldHint is False
            result = await session.call_tool("submit_task", {
                "workspace": ".", "instruction": "x", "acceptance": ["x"],
            })
            assert result.isError
            assert "DEEPSEEK_API_KEY" in str(result.content)
            for name in ["get_task", "wait_task", "cancel_task", "continue_task"]:
                args = {"task_id": "invalid"}
                if name == "continue_task":
                    args["feedback"] = "x"
                response = await session.call_tool(name, args)
                assert response.isError


async def test_full_mcp_task_lifecycle(settings):
    env = {**os.environ, "HARNESS_MCP_ROOT": str(settings.root),
           "DEEPSEEK_API_KEY": "offline-mcp-test-secret"}
    params = StdioServerParameters(
        command=sys.executable, args=[str(FAKE.with_name("fake_mcp_server.py"))], env=env,
    )

    def unpack(result):
        assert not result.isError, result
        return result.structuredContent

    async def wait(session, tid):
        for _ in range(100):
            result = unpack(await session.call_tool("get_task", {"task_id": tid}))
            if result["status"] not in {"queued", "running"}:
                return result
            await asyncio.sleep(0.03)
        pytest.fail("MCP fake task did not complete")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            submitted = unpack(await session.call_tool("submit_task", {
                "workspace": ".", "instruction": "FAKE_EDIT", "acceptance": ["write file"],
            }))
            tid = submitted["task_id"]
            first = await wait(session, tid)
            assert first["status"] == "completed"
            await session.call_tool("continue_task", {"task_id": tid, "feedback": "repeat"})
            second = await wait(session, tid)
            assert second["round"] == 2
            assert first["session_id"] == second["session_id"]
            assert (settings.root / "generated.txt").read_text() == "2"
            worker_pid = second["worker_pid"]
            cancelled = unpack(await session.call_tool("cancel_task", {"task_id": tid}))
            assert cancelled["stopped_confirmed"] is True
            assert worker_pid and not psutil.pid_exists(worker_pid)


async def test_reopen_completed_session_is_rejected(settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-reopen-secret")
    first = HarnessRunner(settings, [sys.executable, str(FAKE)])
    result = await first.submit(".", "FAKE_EDIT", ["x"])
    await finished(first)
    await first.close()
    second = HarnessRunner(settings, [sys.executable, str(FAKE)])
    try:
        with pytest.raises(ValueError, match="cannot resume"):
            await second.continue_task(result["task_id"], "new worker")
        state = second.store.get(result["task_id"])
        assert state.session_id == result["session_id"]
        assert state.round == 1
        assert state.status == "completed"
    finally:
        await second.close()


def test_symlink_escape(settings):
    link = settings.root / "escape"
    try:
        link.symlink_to(settings.root.parent, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit directory symlinks")
    with pytest.raises(ValueError, match="within"):
        settings.workspace("escape")


async def test_shutdown_active_job(runner):
    task = await runner.submit(".", "FAKE_HANG", ["stop"])
    await asyncio.sleep(0.2)
    await runner.close()
    state = runner.store.get(task["task_id"])
    assert state.status == "cancelled"
    assert state.stopped_confirmed


async def test_stale_worker_recovery(settings):
    import subprocess

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    created = process_identity(process.pid)
    tid = uuid.uuid4().hex
    TaskStore(settings).save(Task(tid, ".", "x", ["x"], tid, "test", status="running",
                                  worker_pid=process.pid, worker_created=created))
    bridge = None
    try:
        bridge = HarnessRunner(settings)
        assert bridge.store.get(tid).status == "interrupted"
        assert bridge.store.get(tid).stopped_confirmed
        assert not psutil.pid_exists(process.pid)
    finally:
        if bridge:
            await bridge.close()
        if process.poll() is None:
            process.kill()
        process.wait()


async def test_wait_task_events_terminal_and_timeout(runner):
    task = await runner.submit(".", "FAKE_EDIT", ["x"])
    first = await runner.wait(task["task_id"], cursor=task["next_cursor"], timeout_sec=2)
    assert first["wait_reason"] in {"events", "terminal"}
    job = runner.jobs.get(task["task_id"])
    if job:
        await asyncio.wait_for(asyncio.shield(job), 15)
    terminal = await runner.wait(
        task["task_id"], cursor=runner.store.view(task["task_id"])["next_cursor"],
        timeout_sec=0,
    )
    assert terminal["status"] == "completed"
    assert terminal["wait_reason"] == "terminal"

    hanging = await runner.submit(".", "FAKE_HANG", ["x"])
    current = runner.store.view(hanging["task_id"])
    timeout = await runner.wait(
        hanging["task_id"], cursor=current["next_cursor"], timeout_sec=0.05,
    )
    assert timeout["wait_reason"] in {"events", "timeout"}
    await runner.cancel(hanging["task_id"])


async def test_global_slot_limit_queues_extra_task(settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-slot-key")
    bridge = HarnessRunner(
        Settings(settings.root, timeout=10, max_concurrency=2),
        [sys.executable, str(FAKE)],
    )
    try:
        tasks = [await bridge.submit(".", "FAKE_HANG", ["x"]) for _ in range(3)]
        for _ in range(100):
            states = [bridge.store.get(task["task_id"]).status for task in tasks]
            if states.count("running") == 2:
                break
            await asyncio.sleep(0.05)
        assert states.count("running") == 2
        assert states.count("queued") == 1
        await bridge.cancel(next(
            task["task_id"] for task in tasks
            if bridge.store.get(task["task_id"]).status == "running"
        ))
        for _ in range(100):
            states = [bridge.store.get(task["task_id"]).status for task in tasks]
            if states.count("running") == 2:
                break
            await asyncio.sleep(0.05)
        assert states.count("running") == 2
        await asyncio.gather(*(bridge.cancel(task["task_id"]) for task in tasks))
    finally:
        await bridge.close()


async def test_cross_runner_read_cancel_and_continue(settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-cross-runner-key")
    first = HarnessRunner(settings, [sys.executable, str(FAKE)])
    second = HarnessRunner(settings, [sys.executable, str(FAKE)])
    try:
        hanging = await first.submit(".", "FAKE_HANG", ["x"])
        for _ in range(100):
            state = second.store.view(hanging["task_id"])
            if state["status"] == "running":
                break
            await asyncio.sleep(0.05)
        assert state["owner_id"] == first.owner_id
        cancelled = await second.cancel(hanging["task_id"])
        assert cancelled["status"] == "cancelled"
        assert cancelled["stopped_confirmed"] is True
        await asyncio.sleep(0.1)
        assert second.store.get(hanging["task_id"]).status == "cancelled"

        completed = await first.submit(".", "FAKE_EDIT", ["x"])
        await asyncio.wait_for(asyncio.shield(first.jobs[completed["task_id"]]), 15)
        original_pid = first.store.get(completed["task_id"]).worker_pid
        continued = await second.continue_task(completed["task_id"], "continue elsewhere")
        assert continued["session_id"] == completed["session_id"]
        assert continued["round"] == 2
        for _ in range(300):
            state = second.store.get(completed["task_id"])
            if state.status not in {"queued", "running"}:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("cross-runner continuation did not complete")
        assert state.worker_pid == original_pid
        assert second.store.get(completed["task_id"]).status == "completed"
    finally:
        await first.close()
        await second.close()


async def test_owner_close_cancels_remote_queued_continuation(settings, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-close-race-key")
    first = HarnessRunner(settings, [sys.executable, str(FAKE)])
    second = HarnessRunner(settings, [sys.executable, str(FAKE)])
    try:
        completed = await first.submit(".", "FAKE_EDIT", ["x"])
        await asyncio.wait_for(asyncio.shield(first.jobs[completed["task_id"]]), 15)
        first.control_job.cancel()
        await asyncio.gather(first.control_job, return_exceptions=True)
        queued = await second.continue_task(completed["task_id"], "continue elsewhere")
        assert queued["status"] == "queued"
        await first.close()
        state = second.store.get(completed["task_id"])
        assert state.status == "cancelled"
        assert state.stopped_confirmed is True
        assert state.pending_feedback is None
    finally:
        await first.close()
        await second.close()


async def test_two_stdio_servers_share_runtime(settings):
    env = {**os.environ, "HARNESS_MCP_ROOT": str(settings.root)}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "harness_mcp.server"], env=env,
    )
    async with stdio_client(params) as first_streams:
        async with ClientSession(*first_streams) as first:
            await first.initialize()
            async with stdio_client(params) as second_streams:
                async with ClientSession(*second_streams) as second:
                    await second.initialize()
                    expected = {
                        "submit_task", "get_task", "wait_task",
                        "continue_task", "cancel_task",
                    }
                    assert {tool.name for tool in (await first.list_tools()).tools} == expected
                    assert {tool.name for tool in (await second.list_tools()).tools} == expected
