import importlib.util
from pathlib import Path
import tomllib


def test_overrides_preserve_toml_types():
    path = Path(__file__).resolve().parents[1] / "scripts" / "start_codex.py"
    spec = importlib.util.spec_from_file_location("launcher", path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    args = launcher.config_args(Path("C:/project with spaces"), Path("C:/Python/python.exe"))
    parsed = tomllib.loads("\n".join(args[1::2]))["mcp_servers"]["deepseek_harness"]
    assert parsed["args"] == ["-m", "harness_mcp.server"]
    assert isinstance(parsed["env_vars"], list)
    assert parsed["env"]["HARNESS_MCP_ROOT"] == "C:/project with spaces"
    assert parsed["startup_timeout_sec"] == 20
    assert parsed["tools"]["get_task"]["approval_mode"] == "approve"
    assert parsed["tools"]["wait_task"]["approval_mode"] == "approve"
