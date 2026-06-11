"""Daemon entry point: start the HTTP server on a Unix domain socket."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket as _socket
from pathlib import Path

import uvicorn

from orca.daemon.http_api import create_app, create_browser_app
from orca.daemon.lifecycle import (
    DaemonAlreadyRunningError,
    check_daemon_running,
    cleanup_stale_socket,
    find_daemon_using_port,
    pidfile_path,
    remove_browser_port,
    remove_pidfile,
    socket_path,
    write_browser_port,
    write_pidfile,
    write_root_marker,
)
from orca.daemon.manager import RunManager

logger = logging.getLogger(__name__)

DEFAULT_BROWSER_PORT = 7891


def _port_is_free(port: int) -> bool:
    """Return True if 127.0.0.1:port can be bound right now."""
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def _pick_free_port() -> int:
    """Ask the kernel for a free TCP port on 127.0.0.1."""
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _bind_uds(sock_path: Path) -> _socket.socket:
    """Create and bind the daemon UDS with owner-only permissions.

    The UDS is the privileged control surface (start/stop runs, read logs),
    so it must not be world-connectable. Binding here — instead of letting
    uvicorn bind via ``config.uds``, which chmods the socket to 0o666 — lets
    us clamp the mode before the listener ever accepts a connection. The
    daemon dir is clamped to 0o700 as a second layer (it also holds the
    pidfile and browser-port marker).
    """
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(sock_path.parent, 0o700)
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.bind(str(sock_path))
    os.chmod(sock_path, 0o600)
    return sock


def _resolve_browser_port(requested: int | None) -> tuple[int | None, str | None]:
    """Resolve the browser-facing TCP port.

    Returns ``(port, conflict_message)``. ``port`` is ``None`` only if
    the listener should stay disabled. ``conflict_message`` is non-None
    only when the requested port was busy and a fallback was selected —
    callers should surface it via ``logger.warning``.
    """
    if requested is None:
        return None, None
    if _port_is_free(requested):
        return requested, None
    holder = find_daemon_using_port(requested)
    fallback = _pick_free_port()
    if holder is not None:
        msg = (
            f"Browser port {requested} is already held by the orca daemon for {holder}. "
            f"Binding to free port {fallback} instead. "
            f"Set ORCA_DAEMON_TCP_PORT=<port> to override or 'off' to disable."
        )
    else:
        msg = (
            f"Browser port {requested} is in use by another process. "
            f"Binding to free port {fallback} instead. "
            f"Set ORCA_DAEMON_TCP_PORT=<port> to override or 'off' to disable."
        )
    return fallback, msg


async def serve(repo_root: Path) -> None:
    """Start the daemon HTTP server on a Unix domain socket."""
    # 1. Check not already running
    if check_daemon_running(repo_root):
        raise DaemonAlreadyRunningError(pid=0)

    # 2. Clean up stale socket
    cleanup_stale_socket(repo_root)

    # 3. Create RunManager and scan for interrupted runs
    manager = RunManager(repo_root)
    manager.scan_interrupted_runs()

    # 4. Create app, bind the UDS (owner-only), and write pidfile
    app = create_app(manager)
    sock = socket_path(repo_root)
    uds_socket = _bind_uds(sock)
    pf = pidfile_path(repo_root)
    write_pidfile(pf, os.getpid())
    write_root_marker(repo_root)

    # 5. Configure uvicorn (UDS — privileged surface). The pre-bound socket
    # is handed to server.serve() below so uvicorn never re-binds (and never
    # loosens) the 0o600 socket created in _bind_uds.
    config = uvicorn.Config(
        app=app,
        uds=str(sock),
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # 5b. Optional browser-facing TCP listener (form endpoints + SPA only)
    browser_server: uvicorn.Server | None = None
    tcp_port_env = os.environ.get("ORCA_DAEMON_TCP_PORT")
    requested_port: int | None
    if tcp_port_env is None:
        requested_port = DEFAULT_BROWSER_PORT
    elif tcp_port_env.strip() in ("", "0", "off", "false"):
        requested_port = None
    else:
        try:
            requested_port = int(tcp_port_env)
        except ValueError:
            logger.warning("ORCA_DAEMON_TCP_PORT=%r is not an integer; skipping TCP listener", tcp_port_env)
            requested_port = None

    tcp_port, conflict_msg = _resolve_browser_port(requested_port)
    if conflict_msg is not None:
        logger.warning(conflict_msg)

    if tcp_port is not None:
        browser_app = create_browser_app(manager)
        browser_config = uvicorn.Config(
            app=browser_app,
            host="127.0.0.1",
            port=tcp_port,
            log_level="info",
            access_log=False,
        )
        browser_server = uvicorn.Server(browser_config)
        write_browser_port(repo_root, tcp_port)

    # 6. Set up signal handlers with a stop event
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # Start servers
    server_task = asyncio.create_task(server.serve(sockets=[uds_socket]))
    browser_task: asyncio.Task[None] | None = None
    if browser_server is not None:
        browser_task = asyncio.create_task(browser_server.serve())
        logger.info("Browser-facing TCP listener bound to 127.0.0.1:%d", tcp_port)

    # Wait for stop signal
    await stop_event.wait()

    # 7. Graceful shutdown
    logger.info("Stopping all runs...")
    await manager.stop_all()

    server.should_exit = True
    await server_task
    if browser_server is not None and browser_task is not None:
        browser_server.should_exit = True
        await browser_task

    # Cleanup pidfile, socket, and browser-port marker
    remove_pidfile(pf)
    cleanup_stale_socket(repo_root)
    remove_browser_port(repo_root)
    logger.info("Daemon shut down cleanly")
