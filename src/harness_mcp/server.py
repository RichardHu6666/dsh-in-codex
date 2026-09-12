from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from .config import Settings
from .runner import HarnessRunner


@asynccontextmanager
async def lifespan(_server):
    runner = HarnessRunner(Settings.from_env())
    try:
        yield runner
    finally:
        with anyio.CancelScope(shield=True):
            await runner.close()


mcp = FastMCP(
    "dsh-in-codex", lifespan=lifespan,
    instructions=(
        "For every task, explicitly pass the absolute path of the user's current project "
        "as workspace. Never infer it from the MCP installation or server working directory. "
        "Ask if the current project is ambiguous. Only delegate work authorized for that project. "
        "Existing tasks keep their original workspace on continuation. "
        "Use wait_task, inspect actual diffs and independently verify tests."
    ),
)


@mcp.tool(structured_output=True)
async def submit_task(
    workspace: str, instruction: str, acceptance: list[str], ctx: Context,
) -> dict[str, Any]:
    """Start a task in workspace: explicitly pass the absolute current project directory.

    Do not use the service installation directory or infer workspace from the server CWD.
    Multiple tasks may queue or run. Directory selection does not inherit client sandboxing.
    """
    return await ctx.request_context.lifespan_context.submit(workspace, instruction, acceptance)


@mcp.tool(structured_output=True, annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
))
async def get_task(
    task_id: str, ctx: Context, cursor: int = 0, limit: int = 20,
) -> dict[str, Any]:
    """Read task status and paginated evidence. Completed is not independent test verification."""
    return ctx.request_context.lifespan_context.store.view(task_id, cursor, limit)


@mcp.tool(structured_output=True, annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
))
async def wait_task(
    task_id: str, ctx: Context, cursor: int = 0, limit: int = 20, timeout_sec: float = 30,
) -> dict[str, Any]:
    """Wait for task events or a terminal state, then return the same task view."""
    return await ctx.request_context.lifespan_context.wait(
        task_id, cursor, limit, timeout_sec,
    )


@mcp.tool(structured_output=True)
async def continue_task(task_id: str, feedback: str, ctx: Context) -> dict[str, Any]:
    """Send review feedback to the same Harness session. Rejects concurrent execution."""
    return await ctx.request_context.lifespan_context.continue_task(task_id, feedback)


@mcp.tool(structured_output=True)
async def cancel_task(task_id: str, ctx: Context) -> dict[str, Any]:
    """Stop the owned worker tree. Check stopped_confirmed; edits are never rolled back."""
    return await ctx.request_context.lifespan_context.cancel(task_id)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
