"""orca daemon start|stop|status — manage the orca daemon process."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path


def _repo_root(override: Path | None = None) -> Path:
    """Return the repo root — from explicit override or git rev-parse."""
    if override is not None:
        resolved = override.resolve()
        if not resolved.is_dir():
            print(f"Error: --root path does not exist: {resolved}", file=sys.stderr)
            raise SystemExit(1)
        return resolved
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print("Error: not inside a git repository. Use --root to specify the repo.", file=sys.stderr)
        raise SystemExit(1)
    return Path(result.stdout.strip())


def daemon_command(action: str, root: Path | None = None) -> None:
    """Dispatch daemon start/stop/status."""
    from orca.daemon.lifecycle import check_daemon_running, pidfile_path, read_pidfile, send_stop_signal

    repo = _repo_root(root)

    if action == "start":
        if check_daemon_running(repo):
            pid = read_pidfile(pidfile_path(repo))
            print(f"Daemon already running (PID: {pid}).", file=sys.stderr)
            raise SystemExit(1)

        from orca.daemon.server import serve

        print("Starting orca daemon...")
        asyncio.run(serve(repo))

    elif action == "stop":
        if not check_daemon_running(repo):
            print("Daemon is not running.", file=sys.stderr)
            raise SystemExit(1)

        if send_stop_signal(repo):
            print("Stop signal sent to daemon.")
        else:
            print("Failed to send stop signal.", file=sys.stderr)
            raise SystemExit(1)

    elif action == "status":
        if check_daemon_running(repo):
            pid = read_pidfile(pidfile_path(repo))
            print(f"Daemon running (PID: {pid}).")
        else:
            print("Daemon is not running.")
