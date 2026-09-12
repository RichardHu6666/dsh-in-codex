"""Read-only preflight for updating an existing registered installation."""
import json
import sys

from .onboarding import MCP_SERVER_NAME, document, paths, read_file
from .processes import process_matches


def check(request):
    root, config, _ = paths(request)
    entry = document(read_file(config)).get("mcp_servers", {}).get(MCP_SERVER_NAME)
    expected = [request["launcher"], "serve", "--root", str(root)]
    if entry is None or list(entry.get("args", [])) != expected:
        raise ValueError("Registration does not point to this clone/data directory; run setup first.")
    for record in (root / ".runtime" / "tasks").glob("*.json"):
        task = json.loads(record.read_text(encoding="utf-8"))
        for prefix in ("owner", "worker"):
            pid, created = task.get(f"{prefix}_pid"), task.get(f"{prefix}_created")
            if pid and created and process_matches(pid, created):
                raise ValueError("Close MCP owners and workers before updating.")


def main():
    try:
        check(json.load(sys.stdin))
        print("Update preflight passed. Keep all MCP clients closed during update.")
        return 0
    except Exception:
        print("Update preflight failed: check registration and stop MCP owners/workers. "
              "For an older installation, run setup once first.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
