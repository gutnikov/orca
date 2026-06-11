"""orca debug — list active debug-mode pauses with their review URLs.

User-driven escape hatch when the supervising agent doesn't surface the URL.
Prints one paused review per line: `<run_id> <state> <url>`. Exit code is 0
even when nothing is paused (an empty list is normal).
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

from orca.cli._http import daemon_request


def debug_command(root: Path | None = None) -> None:
    """Print active debug-mode pauses (review URLs) for the current repo's daemon."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    sock = socket_path(repo)

    async def _list() -> None:
        resp = await daemon_request(sock, "GET", "/api/runs")
        if resp.status != 200:
            print(f"Error: {resp.error()}", file=sys.stderr)
            raise SystemExit(1)
        runs = resp.json() or []

        paused = []
        for r in runs:
            for review in r.get("debug_reviews", []) or []:
                paused.append((r.get("run_id", ""), review))

        if not paused:
            print("No debug-mode pauses active.")
            return

        print(f"{len(paused)} debug pause{'s' if len(paused) != 1 else ''} awaiting review:")
        print()
        for run_id, review in paused:
            state = review.get("state", "?")
            url = review.get("url", "(daemon browser port unavailable)")
            print(f"  {run_id}")
            print(f"    state: {state}")
            print(f"    open : {url}")
            print()

    asyncio.run(_list())


def debug_command_args(args: Namespace) -> None:
    debug_command(args.root)
