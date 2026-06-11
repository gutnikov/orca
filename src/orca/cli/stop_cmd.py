"""orca stop <run_id> — stop a running workflow."""

from __future__ import annotations

import sys
from pathlib import Path

from orca.cli._http import daemon_request


def stop_command(run_id: str, root: Path | None = None) -> None:
    """POST /api/runs/{run_id}/stop to the daemon."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    sock = socket_path(repo)

    async def _stop() -> None:
        resp = await daemon_request(sock, "POST", f"/api/runs/{run_id}/stop")
        if resp.status == 200:
            print(f"Run stopped: {run_id}")
        else:
            print(f"Error: {resp.error()}", file=sys.stderr)
            raise SystemExit(1)

    asyncio.run(_stop())
