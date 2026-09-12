"""Same MCP server and manager with only the Harness worker substituted."""
import sys
from pathlib import Path

from harness_mcp import server
from harness_mcp.runner import HarnessRunner


def runner(settings):
    return HarnessRunner(settings, [sys.executable, str(Path(__file__).with_name("fake_worker.py"))])


server.HarnessRunner = runner
server.main()
