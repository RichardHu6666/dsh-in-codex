import os
from pathlib import Path
import shutil

import pytest

from harness_mcp.runtime import node_command, sdk_runtime_options


def test_node_runtime_missing_install(tmp_path):
    with pytest.raises(FileNotFoundError, match="runtime missing|Node"):
        node_command(tmp_path)


def test_runtime_mode_is_explicit(monkeypatch):
    monkeypatch.setenv("HARNESS_MCP_RUNTIME", "bundled")
    assert sdk_runtime_options() == {}
    monkeypatch.setenv("HARNESS_MCP_RUNTIME", "invalid")
    with pytest.raises(ValueError, match="node or bundled"):
        sdk_runtime_options()


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher regression")
def test_launcher_uses_git_bash_without_mutating_parent():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "start_codex.py"
    spec = importlib.util.spec_from_file_location("launcher", path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    old_path = os.environ["PATH"]
    child = launcher.launcher_env()
    assert os.environ["PATH"] == old_path
    bash = shutil.which("bash", path=child["PATH"])
    git = shutil.which("git")
    if git and (Path(git).resolve().parents[1] / "bin" / "bash.exe").exists():
        assert bash and not Path(bash).resolve().is_relative_to(Path(os.environ["SYSTEMROOT"]))
