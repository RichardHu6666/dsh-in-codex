import json

import pytest

from harness_mcp.update_check import check


def registration(tmp_path):
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    launcher = str(tmp_path / "bin" / "cli.cjs")
    args = [launcher, "serve", "--root", str(tmp_path)]
    config.write_text('[mcp_servers.dsh-in-codex]\nargs = ' + json.dumps(args),
                      encoding="utf-8")
    return {"root": str(tmp_path), "scope": "project", "launcher": launcher}


def test_update_preflight_preserves_config(tmp_path):
    request = registration(tmp_path)
    config = tmp_path / ".codex" / "config.toml"
    before = config.read_bytes()
    check(request)
    assert config.read_bytes() == before
    request["launcher"] = "wrong"
    with pytest.raises(ValueError, match="Registration"):
        check(request)


def test_update_preflight_rejects_live_worker(tmp_path, monkeypatch):
    request = registration(tmp_path)
    tasks = tmp_path / ".runtime" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "task.json").write_text(json.dumps({"worker_pid": 123, "worker_created": 1}))
    monkeypatch.setattr("harness_mcp.update_check.process_matches", lambda *args: True)
    with pytest.raises(ValueError, match="Close"):
        check(request)
