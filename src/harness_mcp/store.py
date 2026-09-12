from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .config import Settings
from .processes import FileLock, process_matches, stop_owned

ACTIVE = {"queued", "running", "cancelling"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def task_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("invalid task_id")
    return value


@dataclass
class Task:
    task_id: str
    workspace: str
    instruction: str
    acceptance: list[str]
    session_id: str
    model: str
    status: str = "queued"
    round: int = 1
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    final_response: str | None = None
    finish_reason: str | None = None
    error: str | None = None
    stopped_confirmed: bool | None = None
    worker_pid: int | None = None
    worker_created: float | None = None
    owner_pid: int | None = None
    owner_created: float | None = None
    owner_id: str | None = None
    cancel_requested: bool = False
    pending_feedback: str | None = None
    warnings: list[str] = field(default_factory=list)
    execution_backend: str = "sandbox"


class TaskStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.directory = settings.internal("tasks")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.secrets = [
            v for k, v in os.environ.items()
            if v and (k.endswith("_API_KEY") or k.endswith("_TOKEN"))
        ]

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return text

    def path(self, value: str, suffix: str = ".json"):
        return self.settings.internal("tasks", task_id(value) + suffix)

    def task_lock(self, value: str) -> FileLock:
        return FileLock(self.path(value, ".lock"), blocking=True)

    def save(self, task: Task) -> Task:
        task.updated_at = now()
        target = self.path(task.task_id)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        with FileLock(self.settings.internal("state.lock"), blocking=True):
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(self.redact(json.dumps(asdict(task), ensure_ascii=True, indent=2)))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        return task

    def get(self, value: str) -> Task:
        try:
            return Task(**json.loads(self.path(value).read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise ValueError("unknown task_id") from exc

    @staticmethod
    def owner_alive(task: Task) -> bool:
        if not task.owner_pid or not task.owner_created:
            return False
        return process_matches(task.owner_pid, task.owner_created)

    @staticmethod
    def worker_alive(task: Task) -> bool:
        if not task.worker_pid or not task.worker_created:
            return False
        return process_matches(task.worker_pid, task.worker_created)

    def recover(self):
        for path in self.directory.glob("*.json"):
            task = self.get(path.stem)
            if task.status in ACTIVE and not self.owner_alive(task):
                if task.worker_pid and task.worker_created:
                    task.stopped_confirmed = stop_owned(task.worker_pid, task.worker_created)
                    if not task.stopped_confirmed:
                        task.status = "stop_failed"
                        task.error = "Previous worker could not be stopped; manual inspection required."
                        self.save(task)
                        continue
                    task.worker_pid = task.worker_created = None
                task.status = "interrupted"
                task.error = "MCP stopped before recording completion; inspect workspace."
                self.save(task)
                self.event(task, "interrupted", {"reason": task.error})
            elif task.worker_pid and task.worker_created and task.status not in ACTIVE:
                # A completed worker can be safely reused by its owner, but stale
                # workers from a dead owner must not remain attached to the task.
                if not self.owner_alive(task):
                    task.stopped_confirmed = stop_owned(task.worker_pid, task.worker_created)
                    task.worker_pid = task.worker_created = None
                    self.save(task)

    def event(self, task: Task, kind: str, data: object):
        record = {"time": now(), "round": task.round, "kind": kind, "data": data}
        line = self.redact(json.dumps(record, ensure_ascii=True, default=str))
        if len(line) > 32768:
            line = json.dumps({
                "time": now(), "round": task.round, "kind": kind,
                "truncated": True, "data_excerpt": line[:30000],
            })
        path = self.path(task.task_id, ".jsonl")
        if path.exists() and path.stat().st_size > 128 * 1024 * 1024:
            return
        with FileLock(self.settings.internal("state.lock"), blocking=True):
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def view(self, value: str, cursor: int = 0, limit: int = 20) -> dict:
        if cursor < 0 or not 1 <= limit <= 100:
            raise ValueError("cursor must be nonnegative; limit must be 1..100")
        task = self.get(value)
        path = self.path(value, ".jsonl")
        events, next_cursor = [], cursor
        if path.exists():
            with path.open("rb") as stream:
                if cursor > path.stat().st_size:
                    raise ValueError("cursor is past end of log")
                if cursor:
                    stream.seek(cursor - 1)
                    if stream.read(1) != b"\n":
                        raise ValueError("use a next_cursor returned by get_task")
                stream.seek(cursor)
                for _ in range(limit):
                    line = stream.readline()
                    if not line:
                        break
                    events.append(json.loads(line))
                next_cursor = stream.tell()
        return {
            **asdict(task), "events": events, "next_cursor": next_cursor,
            "has_more": path.exists() and next_cursor < path.stat().st_size,
            "verification": "not_independently_verified", "evidence_log": str(path),
            "note": "completed means Harness turn ended, not that acceptance passed.",
        }

    def active_workspace_tasks(self, workspace: str, exclude: str | None = None) -> list[str]:
        result = []
        for path in self.directory.glob("*.json"):
            task = self.get(path.stem)
            if (task.task_id != exclude and task.workspace == workspace
                    and task.status in ACTIVE):
                result.append(task.task_id)
        return sorted(result)

    def claim_continuation(
        self, value: str, owner_pid: int, owner_created: float, owner_id: str,
        *, feedback: str | None = None, preserve_owner: bool = False,
    ) -> Task:
        with self.task_lock(value):
            task = self.get(value)
            if task.status in ACTIVE or task.status in {"stop_failed", "interrupted"}:
                raise ValueError("task is not safely stopped; interrupted sessions need inspection")
            if not preserve_owner:
                task.owner_pid = owner_pid
                task.owner_created = owner_created
                task.owner_id = owner_id
            task.cancel_requested = False
            task.pending_feedback = feedback
            task.round += 1
            task.status = "queued"
            task.final_response = task.finish_reason = task.error = None
            task.stopped_confirmed = None
            self.save(task)
            return task

    def take_owned_continuations(
        self, owner_pid: int, owner_created: float, owner_id: str,
    ) -> list[tuple[Task, str]]:
        claimed = []
        for path in self.directory.glob("*.json"):
            value = path.stem
            with self.task_lock(value):
                task = self.get(value)
                if (
                    task.owner_pid != owner_pid
                    or task.owner_created != owner_created
                    or task.owner_id != owner_id
                    or task.status != "queued"
                    or task.pending_feedback is None
                ):
                    continue
                feedback = task.pending_feedback
                task.pending_feedback = None
                self.save(task)
                claimed.append((task, feedback))
        return claimed

    def request_cancel(self, value: str) -> Task:
        with self.task_lock(value):
            task = self.get(value)
            task.cancel_requested = True
            if task.status in ACTIVE:
                task.status = "cancelling"
            self.save(task)
            return task

    def record_result(self, value: str, message: dict) -> Task | None:
        with self.task_lock(value):
            task = self.get(value)
            if task.cancel_requested:
                return None
            task.final_response = message.get("final_response")
            task.finish_reason = message.get("finish_reason")
            task.status = "completed" if task.finish_reason == "completed" else "failed"
            if task.status == "failed":
                task.error = f"Harness finish_reason={task.finish_reason!r}"
            self.save(task)
            return task
