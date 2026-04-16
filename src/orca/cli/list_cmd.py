"""orca runs / orca logs — list runs and print worker logs."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import aiohttp


def runs_command(root: Path | None = None) -> None:
    """Connect to daemon, GET /api/runs, print table."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    sock = socket_path(repo)

    async def _list() -> None:
        connector = aiohttp.UnixConnector(path=str(sock))
        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.get("http://localhost/api/runs") as resp,
        ):
            runs = await resp.json()

        if not runs:
            print("No runs found.")
            return

        # Print a simple table
        header = f"{'RUN ID':<40} {'STATUS':<14} {'ISSUES':<10} {'CREATED'}"
        print(header)
        print("-" * len(header))
        for r in runs:
            print(f"{r['run_id']:<40} {r['status']:<14} {r['issue_count']:<10} {r['created_at']}")

    asyncio.run(_list())


def logs_command(args: Namespace) -> None:
    """Connect to daemon, GET /api/runs/{run_id}/logs/{tracking_id}?tail=N, print."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(args.root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    sock = socket_path(repo)
    run_id: str = args.run_id
    issue_id: str | None = args.issue_id
    tail: int = args.tail

    async def _logs() -> None:
        if issue_id:
            url = f"http://localhost/api/runs/{run_id}/logs/{issue_id}?tail={tail}"
        else:
            url = f"http://localhost/api/runs/{run_id}/logs?tail={tail}"
        connector = aiohttp.UnixConnector(path=str(sock))
        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.get(url) as resp,
        ):
            if resp.status == 200:
                text = await resp.text()
                print(text)
            else:
                body = await resp.json()
                print(f"Error: {body.get('error', json.dumps(body))}", file=sys.stderr)
                raise SystemExit(1)

    asyncio.run(_logs())
