"""Check the Git index before publication, without printing secret values."""
from __future__ import annotations

from pathlib import PurePosixPath
import re
import subprocess


def main() -> int:
    files = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    blocked = {".runtime", ".venv", "node_modules", ".codex", "work", "__pycache__", "build"}
    patterns = [
        re.compile(rb"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(rb"(?:E:[/\\]RichardHu6666|C:[/\\]Users[/\\]Richard|D:[/\\]Miniconda)", re.I),
    ]
    errors = []
    count = 0
    for name in filter(None, files):
        count += 1
        path = PurePosixPath(name)
        if blocked.intersection(path.parts) or (
            path.name.startswith(".env") and path.name != ".env.example"
        ):
            errors.append(f"{name}: forbidden publication path")
            continue
        data = subprocess.check_output(["git", "show", f":{name}"])
        if any(pattern.search(data) for pattern in patterns):
            errors.append(f"{name}: possible credential or machine-specific path; inspect locally")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Checked {count} indexed files: no blocked paths or known secret patterns.")
    print("Heuristic checks do not replace manual review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
