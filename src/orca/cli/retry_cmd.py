"""orca retry <run_id> <issue_id> — retry a failed issue."""

from __future__ import annotations

import sys
from pathlib import Path

from orca.cli._http import daemon_request


def retry_command(run_id: str, issue_id: str, root: Path | None = None) -> None:
    """POST /api/runs/{run_id}/retry/{issue_id} to the daemon."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    sock = socket_path(repo)

    async def _retry() -> None:
        resp = await daemon_request(sock, "POST", f"/api/runs/{run_id}/retry/{issue_id}")
        if resp.status == 200:
            print(f"Retry requested: {issue_id}")
        else:
            print(f"Error: {resp.error()}", file=sys.stderr)
            raise SystemExit(1)

    asyncio.run(_retry())
