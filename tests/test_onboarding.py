import io
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values
import pytest
import tomlkit

from harness_mcp import onboarding as setup

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def request_data(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "user-codex"))
    root = tmp_path / "project with spaces"
    root.mkdir()
    return {
        "root": str(root), "scope": "project", "node": sys.executable,
        "launcher": str(REPO / "bin" / "cli.cjs"), "key": "offline-test-key", "skill": True,
    }


def apply(data):
    data["revision"] = setup.inspect(data)["revision"]
    return setup.apply(data)


def test_setup_preserves_files_and_is_idempotent(request_data):
    root, config, skill = setup.paths(request_data)
    config.parent.mkdir()
    config.write_text(
        '# keep this comment\nmodel = "existing"\n[mcp_servers.other]\ncommand = "other"\n',
        encoding="utf-8",
    )
    (root / ".env").write_text('# private\nOTHER="line one\nline two"\n', encoding="utf-8")
    (root / ".gitignore").write_text("existing-rule\n", encoding="utf-8")
    result = apply(request_data)
    assert result["changed"] == 4
    assert skill.is_file()
    doc = tomlkit.parse(config.read_text(encoding="utf-8"))
    assert doc["mcp_servers"]["other"]["command"] == "other"
    assert doc["model"] == "existing"
    assert config.read_text(encoding="utf-8").startswith("# keep this comment")
    assert "offline-test-key" not in config.read_text(encoding="utf-8")
    values = dotenv_values(root / ".env", interpolate=False)
    assert values["OTHER"] == "line one\nline two"
    assert values["DEEPSEEK_API_KEY"] == "offline-test-key"
    assert (root / ".gitignore").read_text().startswith("existing-rule\n")
    before = list((root / ".runtime" / "setup-backups").rglob("*"))
    assert apply(request_data)["changed"] == 0
    assert list((root / ".runtime" / "setup-backups").rglob("*")) == before
    if result["credential_protection"] == "posix-600":
        assert (root / ".env").stat().st_mode & 0o777 == 0o600
    else:
        assert result["credential_protection"] == "windows-acl"


def test_user_scope_and_existing_approval_policy(request_data):
    request_data["scope"] = "user"
    root, config, _ = setup.paths(request_data)
    config.parent.mkdir()
    config.write_text(
        '[mcp_servers.deepseek_harness]\nurl = "https://old.invalid"\n'
        '[mcp_servers.deepseek_harness.tools.submit_task]\napproval_mode = "prompt"\n'
        '[mcp_servers.deepseek_harness.env]\nDEEPSEEK_API_KEY = "old-fixture"\n',
        encoding="utf-8",
    )
    apply(request_data)
    entry = tomlkit.parse(config.read_text())["mcp_servers"]["deepseek_harness"]
    assert entry["args"][-1] == str(root)
    assert entry["tools"]["submit_task"]["approval_mode"] == "prompt"
    assert "url" not in entry
    assert "DEEPSEEK_API_KEY" not in entry["env"]
    assert entry["env"]["HARNESS_MCP_WORKSPACE_MODE"] == "dynamic"
    assert setup.paths(request_data)[2].is_relative_to(config.parent / "skills")
    assert not (root / ".codex" / "config.toml").exists()


def test_changed_file_rejects_stale_confirmation(request_data):
    root, config, _ = setup.paths(request_data)
    request_data["revision"] = setup.inspect(request_data)["revision"]
    (root / ".gitignore").write_text("user edit\n")
    with pytest.raises(setup.SetupError, match="变化"):
        setup.apply(request_data)
    assert not config.exists()
    assert not (root / ".env").exists()


def test_tracked_env_is_rejected(request_data):
    root, _, _ = setup.paths(request_data)
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".env").write_text("DEEPSEEK_API_KEY=fixture\n")
    subprocess.run(["git", "-C", str(root), "add", "-f", ".env"], check=True)
    assert setup.inspect(request_data)["env_tracked"]
    with pytest.raises(setup.SetupError, match="跟踪"):
        apply(request_data)


def test_broken_toml_is_not_rewritten(request_data):
    root, config, _ = setup.paths(request_data)
    config.parent.mkdir()
    config.write_text("[broken")
    with pytest.raises(setup.SetupError, match="TOML"):
        setup.inspect(request_data)
    assert config.read_text() == "[broken"
    assert not (root / ".env").exists()


def test_failed_write_restores_originals(request_data, monkeypatch):
    root, config, _ = setup.paths(request_data)
    (root / ".gitignore").write_text("keep\n")
    original = setup.atomic_write

    def failing_write(path, data):
        if path == config:
            raise OSError("simulated write failure")
        original(path, data)

    monkeypatch.setattr(setup, "atomic_write", failing_write)
    with pytest.raises(OSError):
        apply(request_data)
    assert (root / ".gitignore").read_text() == "keep\n"
    assert not (root / ".env").exists()
    assert not config.exists()


@pytest.mark.parametrize("key", ["contains'quote", r"contains\slash", 'double"quote', "dollar${X}"])
def test_key_roundtrip_without_interpolation(request_data, key):
    request_data["key"] = key
    request_data["skill"] = False
    apply(request_data)
    text = (Path(request_data["root"]) / ".env").read_text(encoding="utf-8")
    assert dotenv_values(stream=io.StringIO(text), interpolate=False)["DEEPSEEK_API_KEY"] == key


def test_environment_only_setup_and_missing_value(request_data, monkeypatch):
    root, _, _ = setup.paths(request_data)
    (root / ".env").write_text("DEEPSEEK_API_KEY\n")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-fixture")
    info = setup.inspect(request_data)
    assert info["environment_key"] and not info["local_key"]
    request_data.pop("key")
    apply(request_data)
    assert (root / ".env").read_text() == "DEEPSEEK_API_KEY\n"


def test_symlink_config_is_rejected(request_data, tmp_path):
    root, _, _ = setup.paths(request_data)
    other = tmp_path / "external"
    other.mkdir()
    try:
        (root / ".codex").symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit directory symlinks")
    with pytest.raises(setup.SetupError, match="符号链接"):
        setup.inspect(request_data)
