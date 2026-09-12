import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_public_metadata():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert package["name"] == "dsh-in-codex"
    assert package["license"] == project["project"]["license"] == "MIT"
    assert (ROOT / "LICENSE").is_file()
    assert package["version"] == project["project"]["version"]
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    for dependency in lock["packages"].values():
        if dependency.get("resolved"):
            assert dependency["resolved"].startswith("https://registry.npmjs.org/")


def test_config_examples_use_launcher():
    for name in ("codex-windows.toml", "codex-linux.toml"):
        config = tomllib.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
        server = config["mcp_servers"]["dsh-in-codex"]
        assert server["command"] == "node"
        assert server["args"][1:3] == ["serve", "--root"]
        assert server["tool_timeout_sec"] > 60
        assert "DEEPSEEK_API_KEY" not in server.get("env", {})


def test_readme_local_links_exist():
    for name in ("README.md", "DEPLOYMENT.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if "://" not in target and not target.startswith("#"):
                assert (ROOT / target.split("#")[0]).exists(), (name, target)


def test_quick_start_and_deployment_guide_are_shipped():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) <= 80
    assert "npm ci\nnpm run setup" in readme
    assert "DEPLOYMENT.md" in readme
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert "DEPLOYMENT.md" in package["files"]
