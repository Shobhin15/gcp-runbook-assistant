"""MCP server: exposes the triage agent's read-only tools to any MCP client.

Run it locally over stdio, for example from Claude Desktop, Cursor, or the MCP
Inspector, so an assistant you already use can search the runbooks, read a
Cloud Run service's recent errors, and check its rollout status. Each tool is
marked read-only (readOnlyHint) so clients know it changes nothing:

    pip install -r requirements.txt -r requirements-mcp.txt
    GCP_PROJECT=your-project GCP_LOCATION=us-central1 python -m app.mcp_server

The tools are the same ones /triage uses (app/tools.py), with the same
guardrails: read-only, validated arguments, service-name checks, the optional
TRIAGE_SERVICES allow-list, and truncated output.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Callable

from app import agent

SERVER_NAME = "runbook-assistant"
RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"


def make_handlers(toolset: list[agent.Tool]) -> dict[str, Callable[..., dict]]:
    """Wrap each tool so every call is validated and truncated, exactly like the agent loop.

    Kept free of the MCP SDK so it can be unit tested offline.
    """
    handlers: dict[str, Callable[..., dict]] = {}
    for tool in toolset:
        def handler(_tool: agent.Tool = tool, **kwargs) -> dict:
            args = {k: v for k, v in kwargs.items() if v is not None}
            return agent._truncate(_tool.fn(**agent.validate_args(_tool, args)))
        handlers[tool.name] = handler
    return handlers


@lru_cache(maxsize=1)
def _handlers() -> dict[str, Callable[..., dict]]:
    # Built on the first tool call, so the server starts instantly and only
    # needs Google Cloud credentials once a tool is actually used.
    from app import rag, tools, vertex

    index = rag.RunbookIndex(rag.load_runbooks(RUNBOOK_DIR), vertex.make_embedder())
    project, location = os.environ["GCP_PROJECT"], os.getenv("GCP_LOCATION", "us-central1")
    return make_handlers(tools.default_tools(index, project, location))


def build_server():
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp 2.x
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server      # mcp 1.x
    from mcp.types import ToolAnnotations

    server = Server(SERVER_NAME)
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

    @server.tool(annotations=read_only)
    def search_runbooks(query: str) -> dict:
        """Search the team's on-call runbooks. Returns the best-matching sections with their runbook names."""
        return _handlers()["search_runbooks"](query=query)

    @server.tool(annotations=read_only)
    def recent_error_logs(service: str, minutes: int = 30) -> dict:
        """Read the most recent ERROR logs (max 20) for a Cloud Run service over the last 5 to 120 minutes."""
        return _handlers()["recent_error_logs"](service=service, minutes=minutes)

    @server.tool(annotations=read_only)
    def cloud_run_status(service: str) -> dict:
        """Get a Cloud Run service's readiness, latest ready vs latest created revision, and traffic split."""
        return _handlers()["cloud_run_status"](service=service)

    return server


if __name__ == "__main__":
    build_server().run()  # stdio transport
