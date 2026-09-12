from __future__ import annotations

import json
import sys
from dataclasses import asdict

import psutil
from deepseek_harness import DeepSeekHarness

from .processes import install_owner_watchdog, stop_processes
from .runtime import sdk_runtime_options


def emit(kind: str, **data):
    print(json.dumps({"kind": kind, **data}, ensure_ascii=True, default=str), flush=True)


def main():
    startup = json.loads(sys.stdin.readline())
    install_owner_watchdog(startup["parent_pid"], startup["parent_created"])
    harness = DeepSeekHarness(
        dsh_home=startup["dsh_home"], cwd=startup["workspace"],
        runtime_cwd=startup["workspace"], profile="sdk", provider="deepseek-official",
        model=startup["model"], initialize_timeout_seconds=startup["initialize_timeout"],
        shutdown_timeout_seconds=2,
        **sdk_runtime_options(),
    )
    try:
        harness.start()
        emit("ready")
        for line in sys.stdin:
            command = json.loads(line)
            if command["kind"] == "close":
                break
            if command["kind"] != "run":
                raise ValueError("unknown worker command")
            try:
                result = harness.run(
                    command["prompt"], session_id=command["session_id"],
                    on_notification=lambda n: emit("notification", notification=asdict(n)),
                )
                emit("result", session_id=result.session_id,
                     final_response=result.final_response, finish_reason=result.finish_reason)
            except Exception as exc:
                emit("error", error=f"{type(exc).__name__}: {exc}")
                break
    except Exception as exc:
        emit("error", error=f"{type(exc).__name__}: {exc}")
    finally:
        # Give the SDK a chance to flush durable state, then reap leftover tool processes.
        children = psutil.Process().children(recursive=True)
        try:
            harness.close()
        finally:
            stop_processes(children)


if __name__ == "__main__":
    main()
