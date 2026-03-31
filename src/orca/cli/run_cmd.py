"""orca run <task.md> — submit a workflow run to the daemon."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import aiohttp


def run_command(args: Namespace) -> None:
    """Check daemon running, POST /api/runs/start, print run_id or error."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root()
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    task_file: Path = args.task_file
    if not task_file.exists():
        print(f"Error: task file not found: {task_file}", file=sys.stderr)
        raise SystemExit(1)

    sock = socket_path(repo)

    async def _submit() -> None:
        connector = aiohttp.UnixConnector(path=str(sock))
        payload = {
            "task_file": str(task_file.resolve()),
            "workflow": args.workflow,
            "branch": args.branch,
            "base": args.base,
            "max_hops": args.max_hops,
            "max_retries": args.max_retries,
        }
        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.post("http://localhost/api/runs/start", json=payload) as resp,
        ):
            body = await resp.json()
            if resp.status == 200:
                print(f"Run started: {body['run_id']}")
            else:
                print(f"Error: {body.get('error', json.dumps(body))}", file=sys.stderr)
                raise SystemExit(1)

    asyncio.run(_submit())
