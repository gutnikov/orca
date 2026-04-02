"""orca mcp — MCP stdio bridge to the daemon."""

from __future__ import annotations

from pathlib import Path


def mcp_command(root: Path | None = None) -> None:
    """Create an MCP server backed by DaemonClient, run on stdio transport."""
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.mcp_tools import create_mcp_server

    repo = _repo_root(root)
    server = create_mcp_server(repo)
    server.run(transport="stdio")
