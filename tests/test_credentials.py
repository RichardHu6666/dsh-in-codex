import os

from harness_mcp.config import load_local_credentials


def test_env_file_loads_only_provider_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("UNRELATED_TEST_VARIABLE", raising=False)
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=offline-test-value\n"
        "DEEPSEEK_BASE_URL=https://example.invalid\n"
        "UNRELATED_TEST_VARIABLE=not-imported\n", encoding="utf-8",
    )
    load_local_credentials(tmp_path)
    assert os.environ["DEEPSEEK_API_KEY"] == "offline-test-value"
    assert os.environ["DEEPSEEK_BASE_URL"] == "https://example.invalid"
    assert "UNRELATED_TEST_VARIABLE" not in os.environ


def test_env_file_preserves_existing_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "process-value")
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=file-value\n", encoding="utf-8")
    load_local_credentials(tmp_path)
    assert os.environ["DEEPSEEK_API_KEY"] == "process-value"


def test_env_file_missing_is_optional(tmp_path):
    load_local_credentials(tmp_path)
