"""orca run <task.md> — submit a workflow run to the daemon."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import aiohttp


def parse_worker_overrides(raw: list[str] | None) -> dict[str, dict[str, str]]:
    """Parse repeated --override values like 'state.field=value'.

    Returns a nested dict {state: {field: value}}. Repeated flags accumulate;
    the same (state, field) pair specified twice keeps the last value.
    Raises ValueError on malformed entries — caller prints the message.
    """
    overrides: dict[str, dict[str, str]] = {}
    if not raw:
        return overrides
    for entry in raw:
        if "=" not in entry:
            raise ValueError(f"override {entry!r}: expected '<state>.<field>=<value>'")
        key, value = entry.split("=", 1)
        if "." not in key:
            raise ValueError(f"override {entry!r}: key part must be '<state>.<field>' (got {key!r})")
        state_name, field = key.split(".", 1)
        state_name = state_name.strip()
        field = field.strip()
        value = value.strip()
        if not state_name or not field or not value:
            raise ValueError(f"override {entry!r}: empty state, field, or value")
        if field not in ("kind", "model", "effort"):
            raise ValueError(f"override {entry!r}: field {field!r} not allowed (use kind / model / effort)")
        overrides.setdefault(state_name, {})[field] = value
    return overrides


def run_command(args: Namespace) -> None:
    """Check daemon running, POST /api/runs/start, print run_id or error."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(args.root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    task_file: Path = args.task_file
    if not task_file.exists():
        print(f"Error: task file not found: {task_file}", file=sys.stderr)
        raise SystemExit(1)

    try:
        worker_overrides = parse_worker_overrides(getattr(args, "override", None))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    sock = socket_path(repo)

    async def _submit() -> None:
        connector = aiohttp.UnixConnector(path=str(sock))
        payload: dict[str, object] = {
            "task_file": str(task_file.resolve()),
            "workflow": args.workflow,
            "branch": args.branch,
            "base": args.base,
            "run_id": args.run_id,
            "headless": args.headless,
            "max_hops": args.max_hops,
            "max_retries": args.max_retries,
            "debug": args.debug,
        }
        if worker_overrides:
            payload["worker_overrides"] = worker_overrides
        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.post("http://localhost/api/runs/start", json=payload) as resp,
        ):
            body = await resp.json()
            if resp.status in (200, 201):
                print(f"Run started: {body['run_id']}")
            else:
                print(f"Error: {body.get('error', json.dumps(body))}", file=sys.stderr)
                raise SystemExit(1)

    asyncio.run(_submit())
