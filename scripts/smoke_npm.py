"""Verify two npm-launcher clients can discover tools without model calls."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(node: str, launcher: str, root: str):
    params = StdioServerParameters(
        command=node, args=[launcher, "serve", "--root", root],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = sorted(tool.name for tool in (await session.list_tools()).tools)
            assert names == [
                "cancel_task", "continue_task", "get_task", "submit_task", "wait_task",
            ], names
            await asyncio.sleep(1)
            return names


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", default="node")
    parser.add_argument("--launcher", default=str(Path(__file__).resolve().parents[1] / "bin/cli.cjs"))
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    async with asyncio.timeout(60):
        results = await asyncio.gather(*(
            check(args.node, args.launcher, args.root) for _ in range(2)
        ))
    print({"clients": len(results), "tools": results[0], "model_called": False})


if __name__ == "__main__":
    asyncio.run(main())
