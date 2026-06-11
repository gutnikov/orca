"""orca run <task.md> — submit a workflow run to the daemon."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

from orca.cli._http import daemon_request


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


def build_run_payload(args: Namespace, worker_overrides: dict[str, dict[str, str]]) -> dict[str, object]:
    """Build the /api/runs/start request payload.

    --max-hops / --max-retries are only included when the user actually
    passed them; otherwise the workflow YAML's values stay in effect (the
    daemon overrides the config only for non-None values).
    """
    payload: dict[str, object] = {
        "task_file": str(args.task_file.resolve()),
        "workflow": args.workflow,
        "branch": args.branch,
        "base": args.base,
        "run_id": args.run_id,
        "headless": args.headless,
        "debug": args.debug,
    }
    if args.max_hops is not None:
        payload["max_hops"] = args.max_hops
    if args.max_retries is not None:
        payload["max_retries"] = args.max_retries
    if worker_overrides:
        payload["worker_overrides"] = worker_overrides
    return payload


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
    payload = build_run_payload(args, worker_overrides)

    async def _submit() -> None:
        resp = await daemon_request(sock, "POST", "/api/runs/start", json_body=payload)
        if resp.status in (200, 201):
            body = resp.json()
            print(f"Run started: {body['run_id']}")
        else:
            print(f"Error: {resp.error()}", file=sys.stderr)
            raise SystemExit(1)

    asyncio.run(_submit())
