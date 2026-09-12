import pytest

from harness_mcp.evidence import harness_test_evidence


def records(output, error=False):
    command = "python -m unittest discover -v; HARNESS_TEST_EXIT=$LASTEXITCODE"
    data = [
        {"type": "tool/call", "data": {"callId": "c", "name": "pwsh",
                                     "arguments": {"command": command}}},
        {"type": "tool/result", "data": {"message": {"content": [{
            "type": "tool-result", "toolCallId": "c", "isError": error,
            "content": [{"type": "text", "text": output}],
        }]}}},
    ]
    return [{"round": 1, "kind": "harness",
             "data": {"payload": {"sessionId": "s", "event": event}}} for event in data]


def test_requires_correlated_successful_execution():
    evidence = records("Ran 3 tests in 0.001s\n\nOK\nHARNESS_TEST_EXIT=0\n")
    assert harness_test_evidence(evidence, 1, "s")
    assert not harness_test_evidence(evidence[1:], 1, "s")
    assert not harness_test_evidence(evidence, 2, "s")
    assert not harness_test_evidence(evidence, 1, "other")


@pytest.mark.parametrize("output", [
    "error: --profile <name> is required\n[exit code: 1]",
    "Ran 0 tests in 0.001s\nOK\nHARNESS_TEST_EXIT=0\n",
    "Ran 3 tests in 0.001s\nFAILED\nHARNESS_TEST_EXIT=1\n",
    "Ran 3 tests in 0.001s\nOK\n",
    "Ran 3 tests in 0.001s\nOK\nHARNESS_TEST_EXIT=0\n[exit code: 1]",
])
def test_rejects_false_pass(output):
    assert not harness_test_evidence(records(output), 1, "s")


def test_model_prose_is_not_evidence():
    assert not harness_test_evidence([
        {"round": 1, "kind": "result", "data": {
            "final_response": "Ran 3 tests in 0.001s\nOK\nHARNESS_TEST_EXIT=0\n",
        }},
    ], 1, "s")
