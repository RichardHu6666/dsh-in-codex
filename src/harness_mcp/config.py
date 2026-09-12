from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


def load_local_credentials(root: Path) -> None:
    """Read only provider settings; existing process environment takes precedence."""
    path = root / ".env"
    if not path.is_file():
        return
    values = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"):
        value = values.get(name)
        if value and not os.environ.get(name):
            os.environ[name] = value


@dataclass(frozen=True)
class Settings:
    root: Path
    model: str = "deepseek-v4-flash"
    timeout: float = 1800
    initialize_timeout: float = 60
    max_concurrency: int = 8
    workspace_mode: str = "fixed"
    execution_backend: str = "sandbox"

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("HARNESS_MCP_ROOT")
        if not raw or not Path(raw).is_absolute():
            raise ValueError("HARNESS_MCP_ROOT must be an explicit absolute project directory")
        root = Path(raw).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("HARNESS_MCP_ROOT must be a directory")
        load_local_credentials(root)
        timeout = float(os.environ.get("HARNESS_MCP_TIMEOUT", "1800"))
        if not 1 <= timeout <= 86400:
            raise ValueError("HARNESS_MCP_TIMEOUT must be between 1 and 86400 seconds")
        raw_limit = os.environ.get("HARNESS_MCP_MAX_CONCURRENCY", "8")
        try:
            max_concurrency = int(raw_limit)
        except ValueError as exc:
            raise ValueError("HARNESS_MCP_MAX_CONCURRENCY must be an integer") from exc
        if not 1 <= max_concurrency <= 64:
            raise ValueError("HARNESS_MCP_MAX_CONCURRENCY must be between 1 and 64")
        mode = os.environ.get("HARNESS_MCP_WORKSPACE_MODE", "fixed")
        if mode not in {"fixed", "dynamic"}:
            raise ValueError("HARNESS_MCP_WORKSPACE_MODE must be fixed or dynamic")
        backend = os.environ.get("HARNESS_MCP_EXECUTION_BACKEND", "sandbox").strip().lower()
        if backend not in {"sandbox", "direct"}:
            raise ValueError("HARNESS_MCP_EXECUTION_BACKEND must be sandbox or direct")
        return cls(root, os.environ.get("HARNESS_MCP_MODEL", "deepseek-v4-flash"),
                   timeout, 60, max_concurrency, mode, backend)

    @property
    def runtime(self) -> Path:
        path = (self.root / ".runtime").resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(".runtime must not resolve outside the project")
        return path

    def workspace(self, raw: str) -> Path:
        path = Path(raw)
        if self.workspace_mode == "dynamic":
            if not path.is_absolute():
                raise ValueError("dynamic workspace must be an explicit absolute current project path")
            path = path.resolve(strict=True)
            if not path.is_dir() or path == Path(path.anchor):
                raise ValueError("workspace must be an existing project directory, not a filesystem root")
            if path.is_relative_to(self.root) or self.root.is_relative_to(path):
                raise ValueError("workspace must not include the service data directory")
            if any(p in {".runtime", ".venv", ".git"} for p in path.parts):
                raise ValueError("internal directories are not task workspaces")
            return path
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve(strict=True)
        if not path.is_relative_to(self.root) or not path.is_dir():
            raise ValueError("workspace must be an existing directory within HARNESS_MCP_ROOT")
        if any(p in {".runtime", ".venv", ".git"} for p in path.relative_to(self.root).parts):
            raise ValueError("internal directories are not task workspaces")
        return path

    def internal(self, *parts: str) -> Path:
        path = self.runtime.joinpath(*parts).resolve()
        if not path.is_relative_to(self.runtime):
            raise ValueError("runtime path escaped .runtime")
        return path

    @property
    def slots(self) -> Path:
        path = self.internal("slots")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def worker_env(self) -> dict[str, str]:
        # The SDK inherits its environment; omit unrelated provider credentials.
        names = {
            "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE",
            "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "HOME", "USERPROFILE",
            "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "TERM", "SHELL",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE",
            "SSL_CERT_DIR", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
            "HARNESS_MCP_RUNTIME",
            "HARNESS_MCP_NODE_ROOT",
            "HARNESS_MCP_EXECUTION_BACKEND",
        }
        env = {k: v for k, v in os.environ.items() if k.upper() in names}
        temp = self.internal("tmp")
        temp.mkdir(parents=True, exist_ok=True)
        env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp),
                   PYTHONUTF8="1", PYTHONUNBUFFERED="1", HARNESS_MCP_ROOT=str(self.root))
        env["DSH_PERMISSION_MODE"] = (
            "danger-full-access" if self.execution_backend == "direct" else "workspace-write"
        )
        return env
