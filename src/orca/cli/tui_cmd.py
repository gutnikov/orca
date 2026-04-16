"""orca tui — attach TUI to the running daemon."""

from __future__ import annotations

import sys
from pathlib import Path


def tui_command(root: Path | None = None) -> None:
    """Check daemon running, launch OrcaApp connected to daemon."""
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    sock = socket_path(repo)

    try:
        from orca.tui.app import OrcaApp
    except ImportError:
        print("Error: textual is not installed. Install with: uv pip install 'orca[tui]'", file=sys.stderr)
        raise SystemExit(1) from None

    app = OrcaApp.from_daemon(sock_path=sock)
    app.run()
