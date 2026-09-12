import pytest

from harness_mcp.runtime import node_command, sdk_runtime_options


def test_node_runtime_missing_install(tmp_path):
    with pytest.raises(FileNotFoundError, match="runtime missing|Node"):
        node_command(tmp_path)


def test_runtime_mode_is_explicit(monkeypatch):
    monkeypatch.setenv("HARNESS_MCP_RUNTIME", "bundled")
    assert sdk_runtime_options() == {}
    monkeypatch.setenv("HARNESS_MCP_RUNTIME", "invalid")
    with pytest.raises(ValueError, match="node or bundled"):
        sdk_runtime_options()
