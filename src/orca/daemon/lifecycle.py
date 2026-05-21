"""Daemon lifecycle management: pidfile, socket paths, process detection."""

from __future__ import annotations

import hashlib
import os
import signal
from pathlib import Path


class DaemonAlreadyRunningError(Exception):
    """Raised when attempting to start a daemon that is already running."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        super().__init__(f"Daemon already running (PID: {pid})")


def daemon_dir(repo_root: Path) -> Path:
    """Return ~/.orca-state/daemons/{hash}/ for the given repo root."""
    repo_hash = hashlib.sha1(str(repo_root).encode()).hexdigest()[:12]
    return Path.home() / ".orca-state" / "daemons" / repo_hash


def socket_path(repo_root: Path) -> Path:
    """Return the UDS socket path for the given repo."""
    return daemon_dir(repo_root) / "daemon.sock"


def pidfile_path(repo_root: Path) -> Path:
    """Return the pidfile path for the given repo."""
    return daemon_dir(repo_root) / "daemon.pid"


def write_pidfile(path: Path, pid: int) -> None:
    """Create parent dirs and write pid as text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid) + "\n")


def read_pidfile(path: Path) -> int | None:
    """Return the PID from a pidfile, or None if missing/invalid."""
    try:
        text = path.read_text().strip()
        return int(text)
    except (FileNotFoundError, ValueError):
        return None


def remove_pidfile(path: Path) -> None:
    """Remove the pidfile if it exists."""
    path.unlink(missing_ok=True)


def _is_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID is alive using os.kill(pid, 0)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return True
    return True


def check_daemon_running(repo_root: Path) -> bool:
    """Check if the daemon is running. Cleans up stale pidfile if process is dead."""
    pf = pidfile_path(repo_root)
    pid = read_pidfile(pf)
    if pid is None:
        return False
    if _is_process_alive(pid):
        return True
    # Stale pidfile -- clean it up
    remove_pidfile(pf)
    return False


def cleanup_stale_socket(repo_root: Path) -> None:
    """Remove the daemon socket file if it exists."""
    sock = socket_path(repo_root)
    sock.unlink(missing_ok=True)


def write_root_marker(repo_root: Path) -> None:
    """Write the repo root path into the daemon dir for reverse lookup."""
    dd = daemon_dir(repo_root)
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "root").write_text(str(repo_root) + "\n")


def read_root_marker(dd: Path) -> Path | None:
    """Read the repo root from a daemon dir's root marker file."""
    root_file = dd / "root"
    try:
        return Path(root_file.read_text().strip())
    except FileNotFoundError:
        return None


def browser_port_path(repo_root: Path) -> Path:
    """Return the path of the file that records this daemon's browser TCP port."""
    return daemon_dir(repo_root) / "browser_port"


def write_browser_port(repo_root: Path, port: int) -> None:
    """Persist the browser-facing TCP port for this daemon."""
    p = browser_port_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(port) + "\n")


def read_browser_port(repo_root: Path) -> int | None:
    """Return the recorded browser TCP port for this daemon, or None if absent/invalid."""
    try:
        return int(browser_port_path(repo_root).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def remove_browser_port(repo_root: Path) -> None:
    """Remove the browser-port file if present."""
    browser_port_path(repo_root).unlink(missing_ok=True)


def find_daemon_using_port(port: int) -> Path | None:
    """Return the repo root of any live daemon currently holding ``port``, else None.

    Scans every ``~/.orca-state/daemons/*/browser_port`` file. A daemon counts
    as "using" the port only when its pidfile points at a live process —
    stale registrations from crashed daemons are ignored.
    """
    base = Path.home() / ".orca-state" / "daemons"
    if not base.is_dir():
        return None
    for dd in base.iterdir():
        if not dd.is_dir():
            continue
        try:
            recorded = int((dd / "browser_port").read_text().strip())
        except (FileNotFoundError, ValueError):
            continue
        if recorded != port:
            continue
        pid = read_pidfile(dd / "daemon.pid")
        if pid is None or not _is_process_alive(pid):
            continue
        return read_root_marker(dd)
    return None


def send_stop_signal(repo_root: Path) -> bool:
    """Send SIGTERM to the daemon. Return True if signal was sent, False otherwise."""
    pf = pidfile_path(repo_root)
    pid = read_pidfile(pf)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    return True
