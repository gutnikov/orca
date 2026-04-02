"""orca mcp — MCP stdio bridge to the daemon."""

from __future__ import annotations


def mcp_command() -> None:
    """Create an MCP server and run on stdio transport."""
    from orca.daemon.mcp_tools import create_mcp_server

    server = create_mcp_server()
    server.run(transport="stdio")
