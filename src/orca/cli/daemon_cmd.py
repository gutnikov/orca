"""orca daemon start|stop|status — manage the orca daemon process."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import time
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


def _start_background(repo: Path) -> None:
    """Spawn the daemon as a detached background process."""
    from orca.daemon.lifecycle import check_daemon_running, daemon_dir, read_pidfile

    log_file = daemon_dir(repo) / "daemon.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Resolve the orca executable so this works across install methods (pip, pipx, uv).
    orca_bin = shutil.which("orca") or sys.argv[0]
    cmd = [orca_bin, "--root", str(repo), "daemon", "start", "--foreground"]

    with open(log_file, "a") as lf:
        subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=lf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    # Wait briefly for the daemon to write its pidfile
    for _ in range(20):
        time.sleep(0.1)
        if check_daemon_running(repo):
            pid = read_pidfile(daemon_dir(repo) / "daemon.pid")
            print(f"Daemon started (PID: {pid}). Log: {log_file}")
            return

    print("Daemon did not start in time. Check log:", file=sys.stderr)
    print(f"  {log_file}", file=sys.stderr)
    raise SystemExit(1)


def _auto_update_agent_plugins() -> None:
    """Best-effort background update of orca plugins for Claude Code and Codex.

    Runs `claude plugin update orca@orca` and `codex plugin update orca@orca`
    in detached threads if those CLIs are on PATH. Failures are silent — this
    is a convenience to prevent CLI/plugin version drift, not a hard
    requirement of starting the daemon.

    Opt out by setting ORCA_NO_AUTO_UPDATE=1 in the environment.
    """
    import os
    import shutil
    import subprocess
    import threading

    if os.environ.get("ORCA_NO_AUTO_UPDATE"):
        return

    def _update(cli_name: str) -> None:
        if not shutil.which(cli_name):
            return
        try:
            result = subprocess.run(
                [cli_name, "plugin", "update", "orca@orca"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                # Print at most one line so users can see what happened without
                # cluttering the daemon start output. Restart hint included
                # because the running editor still holds the old SKILL.
                print(
                    f"orca: refreshed {cli_name} plugin (restart {cli_name} to load the new SKILL)",
                    file=sys.stderr,
                )
        except Exception:
            # Air-gapped, network down, locked cache — silently skip. The
            # user can run the update manually if they care.
            return

    for cli in ("claude", "codex"):
        threading.Thread(target=_update, args=(cli,), daemon=True).start()


def daemon_command(action: str, root: Path | None = None, *, foreground: bool = False) -> None:
    """Dispatch daemon start/stop/status."""
    from orca.daemon.lifecycle import check_daemon_running, pidfile_path, read_pidfile, send_stop_signal

    repo = _repo_root(root)

    if action == "start":
        if check_daemon_running(repo):
            pid = read_pidfile(pidfile_path(repo))
            print(f"Daemon already running (PID: {pid}).", file=sys.stderr)
            raise SystemExit(1)

        # Kick off plugin auto-update in the background BEFORE starting the
        # daemon. This way the CLI flow doesn't wait on it, and any "restart
        # claude" hint lands before the user starts interacting with the run.
        _auto_update_agent_plugins()

        if foreground:
            from orca.daemon.server import serve

            print("Starting orca daemon...")
            asyncio.run(serve(repo))
        else:
            _start_background(repo)

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
            from orca.daemon.lifecycle import read_browser_port

            pid = read_pidfile(pidfile_path(repo))
            port = read_browser_port(repo)
            print(f"Daemon running (PID: {pid}).")
            if port is not None:
                print(f"Browser: http://127.0.0.1:{port}/")
            else:
                print("Browser: disabled (ORCA_DAEMON_TCP_PORT=off).")
        else:
            print("Daemon is not running.")
