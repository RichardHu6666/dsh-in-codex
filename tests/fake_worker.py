"""Deterministic worker double. Never contacts a provider."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

startup = json.loads(sys.stdin.readline())


def emit(kind, **data):
    print(json.dumps({"kind": kind, **data}), flush=True)


emit("ready")
sessions = {}
for line in sys.stdin:
    command = json.loads(line)
    if command["kind"] == "close":
        break
    sid = command["session_id"]
    sessions[sid] = sessions.get(sid, 0) + 1
    prompt = command["prompt"]
    if "FAKE_ERROR" in prompt:
        emit("error", error="simulated Harness failure")
        continue
    if "FAKE_EOF" in prompt:
        sys.exit(2)
    if "FAKE_HANG" in prompt:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(300)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        emit("notification", notification={"child_pid": child.pid})
        time.sleep(300)
    if "FAKE_EDIT" in prompt:
        Path(startup["workspace"], "generated.txt").write_text(
            str(sessions[sid]), encoding="utf-8"
        )
    emit("notification", notification={
        "method": "session.event", "payload": {"sessionId": sid, "event": {
            "type": "tool/result", "data": {"command": "fake test", "exit_code": 0},
        }},
    })
    emit("result", session_id=sid, finish_reason="completed",
         final_response=json.dumps({
             "round_seen": sessions[sid], "pid": os.getpid(),
             "workspace": startup["workspace"], "dsh_home": startup["dsh_home"],
             "sdk_profile": "sdk", "secret_echo": os.environ.get("DEEPSEEK_API_KEY"),
         }))
