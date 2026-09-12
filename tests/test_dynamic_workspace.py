import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

from harness_mcp.config import Settings
from harness_mcp.runner import HarnessRunner


@pytest.fixture
def tmp_path():
    # Dynamic mode rejects any .runtime ancestor, including pytest's default tree.
    base = Path(__file__).resolve().parents[1] / "work"
    base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dynamic-test-", dir=base) as directory:
        yield Path(directory)


async def test_global_tasks_use_distinct_project_directories(tmp_path, monkeypatch):
    data = tmp_path / "service-data"
    data.mkdir()
    projects = [tmp_path / name for name in ("project-a", "project-b")]
    for project in projects:
        project.mkdir()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-dynamic-fixture")
    settings = Settings(data, workspace_mode="dynamic")
    runner = HarnessRunner(settings, [sys.executable, str(Path(__file__).with_name("fake_worker.py"))])
    try:
        tasks = [await runner.submit(str(p), "FAKE_EDIT", ["write in project"]) for p in projects]
        await asyncio.wait_for(asyncio.gather(*runner.jobs.values()), 15)
        for task, project in zip(tasks, projects):
            stored = runner.store.get(task["task_id"])
            assert stored.workspace == str(project.resolve())
            assert Path(json.loads(stored.final_response)["workspace"]) == project.resolve()
            assert (project / "generated.txt").read_text() == "1"
        await runner.continue_task(tasks[0]["task_id"], "second round")
        await asyncio.wait_for(runner.jobs[tasks[0]["task_id"]], 15)
        assert (projects[0] / "generated.txt").read_text() == "2"
        assert (projects[1] / "generated.txt").read_text() == "1"
        assert not (data / "generated.txt").exists()
    finally:
        await runner.close()


def test_dynamic_paths_require_explicit_project(tmp_path):
    data = tmp_path / "service"
    data.mkdir()
    settings = Settings(data, workspace_mode="dynamic")
    for raw in (".", "", str(data), str(tmp_path), str(Path(tmp_path.anchor))):
        with pytest.raises(ValueError):
            settings.workspace(raw)
    internal = tmp_path / "project" / ".git"
    internal.mkdir(parents=True)
    with pytest.raises(ValueError):
        settings.workspace(str(internal))
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError):
        Settings(data).workspace(str(other))


def test_mode_environment_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MCP_ROOT", str(tmp_path))
    monkeypatch.setenv("HARNESS_MCP_WORKSPACE_MODE", "dynamic")
    assert Settings.from_env().workspace_mode == "dynamic"
    monkeypatch.setenv("HARNESS_MCP_WORKSPACE_MODE", "invalid")
    with pytest.raises(ValueError, match="fixed or dynamic"):
        Settings.from_env()


def test_execution_backend_defaults_to_fail_closed_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MCP_ROOT", str(tmp_path))
    monkeypatch.delenv("HARNESS_MCP_EXECUTION_BACKEND", raising=False)
    monkeypatch.setenv("DSH_PERMISSION_MODE", "danger-full-access")
    settings = Settings.from_env()
    assert settings.execution_backend == "sandbox"
    assert settings.worker_env()["DSH_PERMISSION_MODE"] == "workspace-write"


def test_direct_execution_requires_explicit_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MCP_ROOT", str(tmp_path))
    monkeypatch.setenv("HARNESS_MCP_EXECUTION_BACKEND", "direct")
    settings = Settings.from_env()
    assert settings.execution_backend == "direct"
    assert settings.worker_env()["DSH_PERMISSION_MODE"] == "danger-full-access"


def test_execution_backend_rejects_unknown_value(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MCP_ROOT", str(tmp_path))
    monkeypatch.setenv("HARNESS_MCP_EXECUTION_BACKEND", "auto")
    with pytest.raises(ValueError, match="sandbox or direct"):
        Settings.from_env()
