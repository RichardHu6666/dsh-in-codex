from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

import psutil


class FileLock:
    """Cross-process byte-range lock, released by the OS after process death."""

    def __init__(self, path: Path, blocking: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b"\0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                msvcrt.locking(self.file.fileno(), mode, 1)
            else:
                import fcntl
                mode = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
                fcntl.flock(self.file, mode)
        except OSError as exc:
            self.file.close()
            raise RuntimeError("file lock is busy") from exc

    def close(self):
        if self.file.closed:
            return
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class SlotLease(FileLock):
    """A lock held for the lifetime of one Harness worker."""


def process_identity(pid: int | None = None) -> float:
    """Return a stable process-start identity suitable for detecting PID reuse."""
    value = os.getpid() if pid is None else pid
    stat = Path(f"/proc/{value}/stat")
    if os.name != "nt" and stat.is_file():
        # Field 22 is the process start time in clock ticks since boot. Unlike
        # psutil.create_time(), it does not inherit WSL's drifting boot epoch.
        fields = stat.read_text(encoding="ascii").rsplit(") ", 1)[1].split()
        return float(fields[19])
    return psutil.Process(value).create_time()


def process_matches(pid: int, created: float) -> bool:
    try:
        return process_identity(pid) == created and psutil.Process(pid).is_running()
    except (IndexError, OSError, ValueError, psutil.Error):
        return False


def stop_tree(pid: int, include_parent: bool = True) -> bool:
    parent = None
    try:
        parent = psutil.Process(pid)
        if include_parent:
            parent.suspend()
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        return True
    except psutil.AccessDenied:
        if parent and include_parent:
            try:
                parent.resume()
            except psutil.Error:
                pass
        return False
    return stop_processes(children + ([parent] if include_parent else []))


def stop_owned(pid: int, created: float) -> bool:
    try:
        actual_created = process_identity(pid)
    except (FileNotFoundError, ProcessLookupError, psutil.NoSuchProcess):
        return True
    except (IndexError, OSError, ValueError, psutil.AccessDenied):
        return False
    if actual_created != created:
        return True
    return stop_tree(pid)


def stop_processes(targets: list[psutil.Process]) -> bool:
    for proc in targets:
        try:
            proc.suspend()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    for proc in targets:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            try:
                proc.resume()
            except psutil.Error:
                pass
    _, alive = psutil.wait_procs(targets, timeout=5)
    for proc in alive:
        try:
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                return False
        except psutil.NoSuchProcess:
            pass
    return True


def install_owner_watchdog(parent_pid: int, parent_created: float):
    def watch():
        while True:
            time.sleep(1)
            try:
                parent = psutil.Process(parent_pid)
                actual_created = process_identity(parent_pid)
                actual_status = parent.status()
                if (
                    actual_created == parent_created
                    and parent.is_running()
                    and actual_status != psutil.STATUS_ZOMBIE
                ):
                    continue
                detail = (
                    f"pid={parent_pid}, expected_created={parent_created!r}, "
                    f"actual_created={actual_created!r}, status={actual_status}"
                )
            except (OSError, ValueError, psutil.Error) as exc:
                detail = f"pid={parent_pid}, error={type(exc).__name__}: {exc}"
            print(
                f"owner watchdog: owning MCP process is no longer alive ({detail})",
                file=sys.stderr,
                flush=True,
            )
            stop_tree(os.getpid(), include_parent=False)
            os._exit(3)
    threading.Thread(target=watch, daemon=True, name="mcp-owner-watchdog").start()
    if os.name != "nt":
        def terminate(_signum, _frame):
            print("worker received SIGTERM", file=sys.stderr, flush=True)
            stop_tree(os.getpid(), include_parent=False)
            os._exit(143)
        signal.signal(signal.SIGTERM, terminate)
