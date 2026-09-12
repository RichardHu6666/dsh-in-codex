"""Local setup transactions and a non-billable check of the registered MCP."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

from dotenv import dotenv_values
from dotenv.parser import parse_stream
import tomlkit

from .config import Settings
from .processes import FileLock


class SetupError(Exception):
    pass


MCP_SERVER_NAME = "dsh-in-codex"
LEGACY_MCP_SERVER_NAMES = ("deepseek_harness",)


def mcp_servers(doc):
    return doc.get("mcp_servers", {})


def configured_entry(doc):
    servers = mcp_servers(doc)
    if MCP_SERVER_NAME in servers:
        return servers[MCP_SERVER_NAME]
    for legacy in LEGACY_MCP_SERVER_NAMES:
        if legacy in servers:
            return servers[legacy]
    return None


def paths(request: dict) -> tuple[Path, Path, Path]:
    raw = Path(request["root"])
    if not raw.is_absolute() or not raw.is_dir():
        raise SetupError("任务根目录必须是已经存在的绝对路径。")
    root = raw.resolve()
    if root == Path(root.anchor):
        raise SetupError("不能将磁盘根目录作为任务根目录。")
    scope = request["scope"]
    if scope not in {"user", "project"}:
        raise SetupError("无效的配置范围。")
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
    config = (home if scope == "user" else root / ".codex") / "config.toml"
    skill_base = home / "skills" if scope == "user" else root / ".agents" / "skills"
    skill = skill_base / "delegate-deepseek-harness" / "SKILL.md"
    return root, config, skill


def read_file(path: Path) -> bytes | None:
    if path.resolve() != path.absolute():
        raise SetupError("配置文件或上级目录包含符号链接/重定向，请改用独立的真实目录。")
    if path.exists() and not path.is_file():
        raise SetupError("配置目标不是普通文件。")
    return path.read_bytes() if path.exists() else None


def files(request: dict) -> dict[Path, bytes | None]:
    root, config, skill = paths(request)
    return {p: read_file(p) for p in (root / ".env", root / ".gitignore", config, skill)}


def revision(snapshot: dict[Path, bytes | None]) -> str:
    digest = hashlib.sha256()
    for name, content in snapshot.items():
        digest.update(str(name).encode())
        digest.update(b"\0missing" if content is None else b"\0present" + content)
    return digest.hexdigest()


def env_tracked(root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", ".env"],
        capture_output=True, timeout=10,
    )
    if result.returncode not in {0, 1, 128}:
        raise SetupError("无法检查 .env 的 Git 跟踪状态。")
    return result.returncode == 0


def document(data: bytes | None):
    try:
        return tomlkit.parse((data or b"").decode("utf-8-sig"))
    except Exception:
        raise SetupError("现有 Codex TOML 格式无效，未修改文件。") from None


def inspect(request: dict) -> dict:
    root, config, _ = paths(request)
    snapshot = files(request)
    doc = document(snapshot[config])
    values = dotenv_values(
        stream=io.StringIO((snapshot[root / ".env"] or b"").decode("utf-8-sig")),
        interpolate=False,
    )
    return {
        "config_path": str(config),
        "revision": revision(snapshot),
        "existing_mcp": configured_entry(doc) is not None,
        "legacy_mcp": any(name in doc.get("mcp_servers", {}) for name in LEGACY_MCP_SERVER_NAMES),
        "local_key": bool((values.get("DEEPSEEK_API_KEY") or "").strip()),
        "environment_key": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
        "env_tracked": env_tracked(root),
    }


def restrict(path: Path) -> str:
    translated = str(path)
    whoami, icacls = "whoami", "icacls"
    if os.name != "nt":
        path.chmod(0o600)
        if path.stat().st_mode & 0o077 == 0:
            return "posix-600"
        whoami = shutil.which("whoami.exe")
        icacls = shutil.which("icacls.exe")
        wslpath = shutil.which("wslpath")
        if not all((whoami, icacls, wslpath)):
            raise SetupError("文件系统不支持私密文件权限，请使用 Linux 原生目录或可用的 Windows ACL。")
        translated = subprocess.check_output(
            [wslpath, "-w", str(path)], text=True, timeout=10,
        ).strip()
    result = subprocess.run(
        [whoami, "/user", "/fo", "csv", "/nh"], capture_output=True,
        check=True, timeout=10,
    )
    match = re.search(rb"S-1-[0-9-]+", result.stdout)
    if not match:
        raise SetupError("无法识别 Windows 当前用户 SID，未写入密钥。")
    sid = match.group().decode("ascii")
    subprocess.run(
        [icacls, translated, "/inheritance:r", "/grant:r", f"*{sid}:(F)"],
        capture_output=True, check=True, timeout=10,
    )
    return "windows-acl"


def atomic_write(path: Path, data: bytes) -> None:
    read_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".dsh-setup-", dir=path.parent)
    temp = Path(name)
    try:
        # Restrict the empty file before any secrets are written.
        with os.fdopen(fd, "wb") as stream:
            restrict(temp)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def config_bytes(data: bytes | None, request: dict) -> bytes:
    root, _, _ = paths(request)
    doc = document(data)
    servers = doc.setdefault("mcp_servers", tomlkit.table())
    entry = configured_entry(doc)
    if entry is None:
        entry = tomlkit.table()
    elif MCP_SERVER_NAME not in servers:
        # Migrate the old user-facing key without changing its settings.
        for legacy in LEGACY_MCP_SERVER_NAMES:
            if legacy in servers:
                del servers[legacy]
                break
    servers[MCP_SERVER_NAME] = entry
    # Replace transport selection, not other servers or this server's approval policy.
    for field in ("url", "http_headers", "env_http_headers", "bearer_token_env_var"):
        entry.pop(field, None)
    entry["command"] = request["node"]
    entry["args"] = [request["launcher"], "serve", "--root", str(root)]
    entry["enabled"] = True
    entry["startup_timeout_sec"] = max(60, entry.get("startup_timeout_sec", 0))
    entry["tool_timeout_sec"] = max(70, entry.get("tool_timeout_sec", 0))
    existing = list(entry.get("env_vars", []))
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
        if name not in existing:
            existing.append(name)
    entry["env_vars"] = existing
    env = entry.setdefault("env", tomlkit.table())
    env.pop("DEEPSEEK_API_KEY", None)
    env.pop("HARNESS_MCP_ROOT", None)
    env["HARNESS_MCP_WORKSPACE_MODE"] = "dynamic" if request["scope"] == "user" else "fixed"
    return tomlkit.dumps(doc).encode("utf-8")


def apply(request: dict) -> dict:
    root, config, skill = paths(request)
    snapshot = files(request)
    if env_tracked(root):
        raise SetupError(".env 已被 Git 跟踪，请先处理跟踪和密钥风险。")
    if request.get("revision") != revision(snapshot):
        raise SetupError("配置在确认期间发生变化，请重新运行 setup。")
    for field in ("node", "launcher"):
        value = Path(request[field])
        if not value.is_absolute() or not value.is_file():
            raise SetupError("Node 或启动器必须是已存在的绝对文件路径。")
    runtime = Settings(root).runtime
    config.parent.mkdir(parents=True, exist_ok=True)
    backups = runtime / "setup-backups" / uuid.uuid4().hex
    with FileLock(runtime / "setup.lock"), FileLock(config.parent / ".dsh-in-codex-setup.lock"):
        if revision(files(request)) != request["revision"]:
            raise SetupError("配置在确认期间发生变化，请重新运行 setup。")
        planned = {config: config_bytes(snapshot[config], request)}
        env_path = root / ".env"
        key = request.get("key")
        if key is not None:
            if not isinstance(key, str) or not key.strip() or any(c in key for c in "\r\n\0"):
                raise SetupError("密钥不能为空或包含换行。")
            # Parse the pinned dotenv format without writing a plaintext intermediate file.
            text = (snapshot[env_path] or b"").decode("utf-8-sig")
            line = "DEEPSEEK_API_KEY='" + key.strip().replace("\\", "\\\\").replace("'", "\\'") + "'\n"
            chunks, replaced = [], False
            for binding in parse_stream(io.StringIO(text)):
                if binding.key == "DEEPSEEK_API_KEY":
                    if not replaced:
                        chunks.append(line)
                    replaced = True
                else:
                    chunks.append(binding.original.string)
            text = "".join(chunks)
            if not replaced:
                text += ("" if not text or text.endswith("\n") else "\n") + line
            planned[env_path] = text.encode("utf-8")
        elif snapshot[env_path] is None:
            planned[env_path] = b"# Credentials may also be supplied through the environment.\n"
        ignore = root / ".gitignore"
        text = (snapshot[ignore] or b"").decode("utf-8-sig")
        rules = [
            "/.env", "/.env.*", "!/.env.example", "/.runtime/", "/.codex/config.toml",
            "/.codex/.dsh-in-codex-setup.lock",
        ]
        if not all(rule in text.splitlines() for rule in rules):
            text += ("" if not text or text.endswith("\n") else "\n")
            text += "\n# dsh-in-codex local configuration\n" + "\n".join(rules) + "\n"
        planned[ignore] = text.encode("utf-8")
        if request.get("skill"):
            source = (Path(request["launcher"]).parent.parent / ".agents" / "skills"
                      / "delegate-deepseek-harness" / "SKILL.md")
            planned[skill] = source.read_bytes()
        changed = [
            p for p in (ignore, env_path, skill, config)
            if p in planned and snapshot[p] != planned[p]
        ]
        # All backups are private and kept beneath the ignored runtime directory.
        for index, name in enumerate(changed):
            if snapshot[name] is not None:
                atomic_write(backups / f"{index}-{name.name}", snapshot[name])
        written = []
        try:
            for name in changed:
                # Catch edits made by tools which do not participate in our setup lock.
                if read_file(name) != snapshot[name]:
                    raise SetupError("写入前检测到其他程序修改了配置，已停止。")
                atomic_write(name, planned[name])
                written.append(name)
            if env_path.exists() and env_path not in written:
                if read_file(env_path) != snapshot[env_path]:
                    raise SetupError("凭证文件在确认期间发生变化，未覆盖。")
                # A fresh private inode also drops pre-existing explicit Windows ACL grants.
                atomic_write(env_path, snapshot[env_path])
            protection = restrict(env_path) if env_path.exists() else None
        except Exception:
            for name in reversed(written):
                if read_file(name) == planned[name]:
                    if snapshot[name] is None:
                        name.unlink()
                    else:
                        atomic_write(name, snapshot[name])
            raise
    return {"changed": len(changed), "config_path": str(config), "credential_protection": protection}


async def verify(request: dict) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root, config, _ = paths(request)
    entry = document(read_file(config))["mcp_servers"][MCP_SERVER_NAME]
    env = {**os.environ, **entry.get("env", {})}
    params = StdioServerParameters(
        command=entry["command"], args=list(entry["args"]), env=env, cwd=str(root),
    )
    async with asyncio.timeout(65):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = sorted(t.name for t in (await session.list_tools()).tools)
                if names != ["cancel_task", "continue_task", "get_task", "submit_task", "wait_task"]:
                    raise SetupError("服务返回的工具列表不符合预期。")
                return {"tools": names, "model_called": False}


def main():
    try:
        request = json.load(sys.stdin)
        action = sys.argv[1]
        if action == "inspect":
            result = inspect(request)
        elif action == "apply":
            result = apply(request)
        elif action == "verify":
            result = asyncio.run(verify(request))
        else:
            raise SetupError("未知配置操作。")
        print(json.dumps(result))
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, SetupError) else (
            f"配置操作失败（{type(exc).__name__}）；请检查依赖、文件权限或配置格式。"
        )
        print(json.dumps({"error": message}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
