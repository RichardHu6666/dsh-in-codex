from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field

from .config import Settings
from .processes import SlotLease, process_identity, stop_owned, stop_tree
from .store import ACTIVE, Task, TaskStore


class TaskAbandoned(Exception):
    pass


@dataclass
class Worker:
    task_id: str
    process: asyncio.subprocess.Process
    slot: SlotLease | None = None
    stderr_job: asyncio.Task | None = None
    ready: bool = False
    stderr_tail: list[str] = field(default_factory=list)


class HarnessRunner:
    """Manage workers owned by this MCP process, coordinated by persistent files."""

    def __init__(self, settings: Settings, worker_command: list[str] | None = None):
        self.settings = settings
        self.store = TaskStore(settings)
        self.store.recover()
        self.command = worker_command or [sys.executable, "-m", "harness_mcp.worker"]
        self.owner_pid = os.getpid()
        self.owner_created = process_identity()
        self.owner_id = uuid.uuid4().hex
        self.workers: dict[str, Worker] = {}
        self.jobs: dict[str, asyncio.Task] = {}
        self.guard = asyncio.Lock()
        self.closing = False
        self.control_job = asyncio.create_task(self._control_loop())

    @staticmethod
    def check_key():
        if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
            raise ValueError("DEEPSEEK_API_KEY is missing; set it in the MCP process environment")

    @staticmethod
    def validate_input(instruction: str, acceptance: list[str]):
        if not instruction.strip() or len(instruction) > 100000:
            raise ValueError("instruction must contain 1..100000 characters")
        if not acceptance or any(not item.strip() for item in acceptance):
            raise ValueError("provide at least one non-empty acceptance criterion")
        if len(acceptance) > 100 or sum(map(len, acceptance)) > 50000:
            raise ValueError("acceptance criteria are too large")

    def owns(self, task: Task) -> bool:
        return (
            task.owner_pid == self.owner_pid
            and task.owner_created == self.owner_created
            and task.owner_id == self.owner_id
        )

    async def submit(self, workspace: str, instruction: str, acceptance: list[str]) -> dict:
        async with self.guard:
            self.check_key()
            self.validate_input(instruction, acceptance)
            path = self.settings.workspace(workspace)
            relative = (str(path) if self.settings.workspace_mode == "dynamic"
                        else path.relative_to(self.settings.root).as_posix())
            tid = uuid.uuid4().hex
            conflicts = self.store.active_workspace_tasks(relative)
            warnings = []
            if conflicts:
                warnings.append(
                    "Concurrent tasks share this workspace: "
                    f"{', '.join(conflicts)}. Coordinate file and test conflicts."
                )
            task = Task(
                tid, relative, instruction, acceptance, f"codex-{tid}", self.settings.model,
                owner_pid=self.owner_pid, owner_created=self.owner_created,
                owner_id=self.owner_id, warnings=warnings,
            )
            self.store.save(task)
            self.store.event(task, "submitted", {"acceptance": acceptance, "warnings": warnings})
            self.jobs[tid] = asyncio.create_task(self._run(tid, self._prompt(task)))
            return self.store.view(tid)

    def _prompt(self, task: Task, feedback: str | None = None) -> str:
        path = self.settings.workspace(task.workspace)
        criteria = "\n".join(f"- {item}" for item in task.acceptance)
        review = f"\nReview feedback for this round:\n{feedback}" if feedback else ""
        return (
            f"Work only in this task workspace: {path}\n"
            "Do not modify .runtime, .venv, credentials, or Git metadata. Do not commit, "
            "push, or merge. Do not read secrets or change global configuration. Inspect and "
            "modify code, add tests, run checks, and report actual results. If input or "
            "permission is needed, report the blocker and stop.\n"
            f"Original task:\n{task.instruction}\nAcceptance:\n{criteria}{review}\n"
            "Return changed paths, test commands with exit status/output, unverified criteria, "
            "and remaining risks. A failed test is not success."
        )

    async def _acquire_slot(self, tid: str) -> SlotLease:
        while True:
            task = self.store.get(tid)
            if task.cancel_requested or not self.owns(task) or task.status not in ACTIVE:
                raise TaskAbandoned
            for index in range(self.settings.max_concurrency):
                try:
                    return SlotLease(self.settings.slots / f"slot-{index}.lock")
                except RuntimeError:
                    continue
            await asyncio.sleep(0.2)

    async def _spawn(self, task: Task, slot: SlotLease) -> Worker:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        process = await asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(self.settings.root),
            env=self.settings.worker_env(), limit=8 * 1024 * 1024, **options,
        )
        worker = Worker(task.task_id, process, slot)
        self.workers[task.task_id] = worker
        created = process_identity(process.pid)
        with self.store.task_lock(task.task_id):
            current = self.store.get(task.task_id)
            if (
                current.cancel_requested
                or current.status != "running"
                or not self.owns(current)
            ):
                raise TaskAbandoned
            current.worker_pid = process.pid
            current.worker_created = created
            self.store.save(current)
        worker.stderr_job = asyncio.create_task(self._stderr(worker))
        home = self.settings.internal("dsh-home", task.task_id)
        home.mkdir(parents=True, exist_ok=True)
        await self._send(worker, {
            "workspace": str(self.settings.workspace(task.workspace)),
            "dsh_home": str(home), "model": task.model,
            "parent_pid": os.getpid(), "parent_created": self.owner_created,
            "initialize_timeout": self.settings.initialize_timeout,
        })
        return worker

    async def _stderr(self, worker: Worker):
        assert worker.process.stderr
        try:
            while line := await worker.process.stderr.readline():
                text = line.decode("utf-8", errors="replace").rstrip()
                worker.stderr_tail.append(text)
                del worker.stderr_tail[:-20]
                self.store.event(self.store.get(worker.task_id), "worker_stderr", text)
        except (ValueError, OSError):
            pass

    @staticmethod
    async def _send(worker: Worker, message: dict):
        assert worker.process.stdin
        worker.process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await worker.process.stdin.drain()

    @staticmethod
    async def _read(worker: Worker) -> dict:
        assert worker.process.stdout
        line = await worker.process.stdout.readline()
        if not line:
            return_code = await worker.process.wait()
            if worker.stderr_job and not worker.stderr_job.done():
                await asyncio.sleep(0)
            detail = f"; stderr: {' | '.join(worker.stderr_tail)}" if worker.stderr_tail else ""
            raise RuntimeError(
                f"worker exited with code {return_code} before returning a result; "
                f"inspect event log{detail}"
            )
        return json.loads(line)

    async def _run(self, tid: str, prompt: str):
        worker = None
        slot = None
        try:
            slot = await self._acquire_slot(tid)
            with self.store.task_lock(tid):
                task = self.store.get(tid)
                if (
                    task.cancel_requested
                    or task.status not in ACTIVE
                    or not self.owns(task)
                ):
                    raise TaskAbandoned
                task.status = "running"
                self.store.save(task)
            worker = self.workers.get(tid)
            if not worker or worker.process.returncode is not None:
                if worker:
                    await self._close_worker(tid, force=True)
                if task.round > 1:
                    raise RuntimeError(
                        "the original SDK worker exited before continuation; "
                        "the sdk profile cannot resume the persisted session"
                    )
                worker = await self._spawn(task, slot)
            else:
                worker.slot = slot
                with self.store.task_lock(tid):
                    task = self.store.get(tid)
                    if (
                        task.cancel_requested
                        or task.status != "running"
                        or not self.owns(task)
                    ):
                        raise TaskAbandoned
                    task.worker_pid = worker.process.pid
                    task.worker_created = process_identity(worker.process.pid)
                    self.store.save(task)
            async with asyncio.timeout(self.settings.timeout):
                if not worker.ready:
                    message = await self._read(worker)
                    if message["kind"] != "ready":
                        raise RuntimeError(message.get("error", "worker failed to initialize"))
                    worker.ready = True
                    self.store.event(task, "ready", {"profile": "sdk"})
                await self._send(worker, {
                    "kind": "run", "session_id": task.session_id, "prompt": prompt,
                })
                while True:
                    message = await self._read(worker)
                    if message["kind"] == "notification":
                        self.store.event(self.store.get(tid), "harness", message["notification"])
                    elif message["kind"] == "error":
                        raise RuntimeError(message["error"])
                    elif message["kind"] == "result":
                        current = self.store.get(tid)
                        if message["session_id"] != current.session_id:
                            raise RuntimeError("worker returned a mismatched session")
                        task = self.store.record_result(tid, message)
                        if task is None:
                            raise TaskAbandoned
                        self.store.event(task, "result", message)
                        break
                    else:
                        raise RuntimeError("invalid worker response kind")
        except (asyncio.CancelledError, TaskAbandoned):
            with self.store.task_lock(tid):
                task = self.store.get(tid)
                if task.status != "cancelled":
                    task.status = "cancelling"
                    self.store.save(task)
            stopped = await self._close_worker(tid, force=True)
            with self.store.task_lock(tid):
                task = self.store.get(tid)
                task.stopped_confirmed = stopped
                task.status = "cancelled" if stopped else "stop_failed"
                task.error = "Cancelled by client or MCP shutdown; inspect partial edits."
                task.worker_pid = task.worker_created = None
                self.store.save(task)
            self.store.event(task, "state", {"status": task.status,
                                             "stopped_confirmed": task.stopped_confirmed})
        except Exception as exc:
            stopped = await self._close_worker(tid, force=True)
            with self.store.task_lock(tid):
                task = self.store.get(tid)
                task.stopped_confirmed = stopped
                if task.cancel_requested:
                    task.status = "cancelled" if stopped else "stop_failed"
                    task.error = "Cancelled by client; inspect partial edits."
                else:
                    task.status = "timed_out" if isinstance(exc, TimeoutError) else "failed"
                    task.error = f"{type(exc).__name__}: {exc}"
                    if not stopped:
                        task.status = "stop_failed"
                task.worker_pid = task.worker_created = None
                self.store.save(task)
            self.store.event(task, "state", {"status": task.status, "error": task.error,
                                             "stopped_confirmed": task.stopped_confirmed})
        finally:
            if worker and worker.slot:
                worker.slot.close()
                worker.slot = None
            elif slot:
                slot.close()
            self.jobs.pop(tid, None)

    async def _control_loop(self):
        try:
            while True:
                for task, feedback in self.store.take_owned_continuations(
                    self.owner_pid, self.owner_created, self.owner_id,
                ):
                    if task.task_id not in self.jobs:
                        self.store.event(task, "continuation_dispatched", {
                            "owner_id": self.owner_id,
                        })
                        self.jobs[task.task_id] = asyncio.create_task(
                            self._run(task.task_id, self._prompt(task, feedback))
                        )
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    async def _close_worker(self, tid: str, force: bool = False) -> bool:
        worker = self.workers.get(tid)
        if not worker:
            return True
        if not force and worker.process.returncode is None:
            try:
                await self._send(worker, {"kind": "close"})
                await asyncio.wait_for(worker.process.wait(), 5)
            except (TimeoutError, BrokenPipeError, ConnectionResetError):
                pass
        stopped = True
        if worker.process.returncode is None:
            stopped = await asyncio.to_thread(stop_tree, worker.process.pid)
        if stopped:
            await worker.process.wait()
            if worker.stderr_job:
                worker.stderr_job.cancel()
                await asyncio.gather(worker.stderr_job, return_exceptions=True)
            self.workers.pop(tid, None)
        return stopped

    async def continue_task(self, value: str, feedback: str) -> dict:
        async with self.guard:
            self.check_key()
            if not feedback.strip() or len(feedback) > 100000:
                raise ValueError("feedback must contain 1..100000 characters")
            task = self.store.get(value)
            self.settings.workspace(task.workspace)
            if task.status in ACTIVE or task.status in {"stop_failed", "interrupted"}:
                raise ValueError(
                    "task is not safely stopped; interrupted sessions need inspection"
                )
            if (
                self.store.worker_alive(task)
                and not self.owns(task)
                and self.store.owner_alive(task)
            ):
                task = self.store.claim_continuation(
                    value, self.owner_pid, self.owner_created, self.owner_id,
                    feedback=feedback, preserve_owner=True,
                )
                self.store.event(task, "continued", {
                    "feedback": feedback,
                    "dispatched_to_owner": task.owner_id,
                })
                return self.store.view(value)
            if not self.store.worker_alive(task):
                raise ValueError(
                    "the original SDK worker is unavailable; the sdk profile cannot resume "
                    "a persisted session in a new process. Inspect the workspace and submit "
                    "a new scoped task"
                )
            task = self.store.claim_continuation(
                value, self.owner_pid, self.owner_created, self.owner_id,
            )
            task.worker_pid = task.worker_created = None
            self.store.save(task)
            self.store.event(task, "continued", {"feedback": feedback})
            self.jobs[value] = asyncio.create_task(self._run(value, self._prompt(task, feedback)))
            return self.store.view(value)

    async def cancel(self, value: str) -> dict:
        async with self.guard:
            task = self.store.request_cancel(value)
            self.store.event(task, "cancel_requested", {})
            job = self.jobs.get(value)
            if job and not job.done():
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
                task = self.store.get(value)
                if task.status == "cancelling":
                    task.status = "cancelled"
                    task.stopped_confirmed = True
                    task.error = "Cancelled before the worker started."
                    self.store.save(task)
                    self.store.event(task, "state", {
                        "status": task.status, "stopped_confirmed": task.stopped_confirmed,
                    })
            elif task.worker_pid and task.worker_created:
                worker_pid = task.worker_pid
                worker_created = task.worker_created
                stopped = await asyncio.to_thread(
                    stop_owned, task.worker_pid, task.worker_created,
                )
                with self.store.task_lock(value):
                    task = self.store.get(value)
                    task.stopped_confirmed = stopped
                    task.status = "cancelled" if stopped else "stop_failed"
                    if (
                        task.worker_pid == worker_pid
                        and task.worker_created == worker_created
                    ):
                        task.worker_pid = task.worker_created = None
                    self.store.save(task)
            else:
                with self.store.task_lock(value):
                    task = self.store.get(value)
                    task.stopped_confirmed = True
                    if task.status in ACTIVE:
                        task.status = "cancelled"
                    self.store.save(task)
            return self.store.view(value)

    async def wait(self, value: str, cursor: int = 0, limit: int = 20,
                   timeout_sec: float = 30) -> dict:
        if not 0 <= timeout_sec <= 60:
            raise ValueError("timeout_sec must be between 0 and 60")
        deadline = time.monotonic() + timeout_sec
        while True:
            result = self.store.view(value, cursor, limit)
            if result["events"] or result["status"] not in ACTIVE:
                result["wait_reason"] = "events" if result["events"] else "terminal"
                return result
            if time.monotonic() >= deadline:
                result["wait_reason"] = "timeout"
                return result
            await asyncio.sleep(min(0.25, deadline - time.monotonic()))

    async def close(self):
        async with self.guard:
            self.closing = True
            self.control_job.cancel()
            await asyncio.gather(self.control_job, return_exceptions=True)
            for job in list(self.jobs.values()):
                if not job.done():
                    job.cancel()
            if self.jobs:
                await asyncio.gather(*self.jobs.values(), return_exceptions=True)
            for tid in list(self.workers):
                stopped = await self._close_worker(tid, force=True)
                with self.store.task_lock(tid):
                    task = self.store.get(tid)
                    if self.owns(task):
                        task.worker_pid = task.worker_created = None
                        task.stopped_confirmed = stopped
                        if task.status in ACTIVE:
                            task.status = "cancelled" if stopped else "stop_failed"
                            task.error = "Owning MCP closed; inspect partial edits."
                            task.pending_feedback = None
                        self.store.save(task)
                if self.owns(task):
                    self.store.event(task, "state", {
                        "status": task.status,
                        "stopped_confirmed": task.stopped_confirmed,
                    })
