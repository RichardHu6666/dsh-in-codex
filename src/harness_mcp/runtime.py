"""Use the official Node CLI without PowerShell/cmd quoting or private SDK APIs."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def sdk_runtime_options() -> dict:
    mode = os.environ.get("HARNESS_MCP_RUNTIME", "node" if os.name == "nt" else "bundled")
    if mode == "bundled":
        return {}
    if mode != "node":
        raise ValueError("HARNESS_MCP_RUNTIME must be node or bundled")
    executable = Path(sys.executable).with_name("harness-dsh.exe" if os.name == "nt" else "harness-dsh")
    if not executable.is_file():
        raise FileNotFoundError("harness-dsh entrypoint missing; reinstall this Python package")
    return {"dsh_bin": str(executable)}


def node_command(root: Path) -> list[str]:
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("Node >=22.19 is required for the node runtime")
    cli = root / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    if not cli.is_file():
        raise FileNotFoundError("Official Node runtime missing; run npm ci in HARNESS_MCP_ROOT")
    return [node, str(cli)]


def main():
    raw_root = os.environ.get("HARNESS_MCP_ROOT")
    if not raw_root or not Path(raw_root).is_absolute():
        raise SystemExit("HARNESS_MCP_ROOT must be an absolute directory")
    if not os.environ.get("DSH_HOME"):
        raise SystemExit("DSH_HOME must be explicit; personal Harness home is never a fallback")
    try:
        node_root = Path(os.environ.get("HARNESS_MCP_NODE_ROOT", raw_root)).resolve()
        command = [*node_command(node_root), *sys.argv[1:]]
        if os.name != "nt":
            os.execvpe(command[0], command, os.environ)
        return subprocess.call(command)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
