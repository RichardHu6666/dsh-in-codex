"""Build TOML overrides without PowerShell native-command quote conversion."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def config_args(root: Path, python: Path) -> list[str]:
    settings = {
        "command": python.as_posix(),
        "args": ["-m", "harness_mcp.server"],
        "env.HARNESS_MCP_ROOT": root.as_posix(),
        "env_vars": [
            "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
            "HARNESS_MCP_MAX_CONCURRENCY",
        ],
        "startup_timeout_sec": 20,
        "tool_timeout_sec": 70,
        "tools.get_task.approval_mode": "approve",
        "tools.wait_task.approval_mode": "approve",
    }
    args = []
    for key, value in settings.items():
        args.extend(["-c", f"mcp_servers.deepseek_harness.{key}={json.dumps(value)}"])
    return args


def main():
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if not executable:
        raise SystemExit("Codex executable was not found in PATH.")
    command = [executable, *config_args(root, Path(sys.executable)), *sys.argv[1:]]
    try:
        return subprocess.call(command, cwd=root, env=launcher_env())
    except KeyboardInterrupt:
        return 130


def launcher_env() -> dict[str, str]:
    env = os.environ.copy()
    if os.name == "nt":
        bash = shutil.which("bash")
        git = shutil.which("git")
        system_root = Path(env.get("SYSTEMROOT", "C:/Windows")).resolve()
        if git and (not bash or Path(bash).resolve().is_relative_to(system_root)):
            git_bin = Path(git).resolve().parents[1] / "bin"
            if (git_bin / "bash.exe").is_file():
                env["PATH"] = str(git_bin) + os.pathsep + env.get("PATH", "")
    return env


if __name__ == "__main__":
    raise SystemExit(main())
