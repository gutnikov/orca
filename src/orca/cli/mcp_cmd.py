"""orca mcp — MCP stdio bridge."""

from __future__ import annotations

import sys


def mcp_command() -> None:
    """Create an in-process RunManager and MCP server, run on stdio transport.

    NOTE: first iteration creates in-process RunManager, not UDS proxy.
    """
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running

    repo = _repo_root()
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    from orca.daemon.manager import RunManager
    from orca.daemon.mcp_tools import create_mcp_server

    manager = RunManager(repo)
    server = create_mcp_server(manager)
    server.run(transport="stdio")
