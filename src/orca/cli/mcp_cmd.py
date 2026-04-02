"""orca mcp — MCP stdio bridge to the daemon."""

from __future__ import annotations

import sys
from pathlib import Path


def mcp_command(root: Path | None = None) -> None:
    """Create an MCP server backed by DaemonClient, run on stdio transport."""
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.client import DaemonClient
    from orca.daemon.lifecycle import check_daemon_running, socket_path
    from orca.daemon.mcp_tools import create_mcp_server

    repo = _repo_root(root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    client = DaemonClient(socket_path(repo))
    server = create_mcp_server(client)
    server.run(transport="stdio")
