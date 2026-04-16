"""orca stop <run_id> — stop a running workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import aiohttp


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
        connector = aiohttp.UnixConnector(path=str(sock))
        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.post(f"http://localhost/api/runs/{run_id}/stop") as resp,
        ):
            body = await resp.json()
            if resp.status == 200:
                print(f"Run stopped: {run_id}")
            else:
                print(f"Error: {body.get('error', json.dumps(body))}", file=sys.stderr)
                raise SystemExit(1)

    asyncio.run(_stop())
