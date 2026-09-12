"""Extract execution evidence, never infer a test pass from the model's final prose."""
from __future__ import annotations

import json
import re


def harness_test_evidence(records: list[dict], round_number: int, session_id: str) -> list[dict]:
    calls = {}
    successes = []
    for record in records:
        if record.get("round") != round_number or record.get("kind") != "harness":
            continue
        payload = record.get("data", {}).get("payload", {})
        if payload.get("sessionId") != session_id:
            continue
        event = payload.get("event", {})
        data = event.get("data", {})
        if event.get("type") == "tool/call":
            arguments = data.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    continue
            if isinstance(arguments, dict):
                calls[data.get("callId")] = (data.get("name"), arguments.get("command", ""))
        elif event.get("type") == "tool/result":
            message = data.get("message", {})
            for block in message.get("content", []):
                if block.get("type") != "tool-result" or block.get("isError"):
                    continue
                name, command = calls.get(block.get("toolCallId"), (None, ""))
                if name not in {"pwsh", "bash"} or not isinstance(command, str):
                    continue
                if not re.search(r"-m\s+unittest\s+discover\b", command):
                    continue
                output = "\n".join(x.get("text", "") for x in block.get("content", [])
                                   if x.get("type") == "text")
                if re.search(r"\[exit code:\s*(?!0\])\S+\]", output):
                    continue
                if not re.search(r"(?m)^HARNESS_TEST_EXIT=0\s*$", output):
                    continue
                if "HARNESS_TEST_EXIT" not in command:
                    continue
                if not re.search(r"Ran [1-9]\d* tests? in ", output):
                    continue
                if not re.search(r"(?m)^OK\s*$", output):
                    continue
                successes.append({"tool": name, "command": command, "output": output,
                                  "call_id": block["toolCallId"]})
    return successes
