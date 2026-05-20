"""Daemon entry point: start the HTTP server on a Unix domain socket."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

import uvicorn

from orca.daemon.http_api import create_app, create_browser_app
from orca.daemon.lifecycle import (
    DaemonAlreadyRunningError,
    check_daemon_running,
    cleanup_stale_socket,
    pidfile_path,
    remove_pidfile,
    socket_path,
    write_pidfile,
    write_root_marker,
)
from orca.daemon.manager import RunManager

logger = logging.getLogger(__name__)


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

    # 4. Create app and write pidfile
    app = create_app(manager)
    sock = socket_path(repo_root)
    sock.parent.mkdir(parents=True, exist_ok=True)
    pf = pidfile_path(repo_root)
    write_pidfile(pf, os.getpid())
    write_root_marker(repo_root)

    # 5. Configure uvicorn (UDS — privileged surface)
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
    tcp_port: int | None
    if tcp_port_env is None:
        tcp_port = 7891
    elif tcp_port_env.strip() in ("", "0", "off", "false"):
        tcp_port = None
    else:
        try:
            tcp_port = int(tcp_port_env)
        except ValueError:
            logger.warning("ORCA_DAEMON_TCP_PORT=%r is not an integer; skipping TCP listener", tcp_port_env)
            tcp_port = None

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

    # 6. Set up signal handlers with a stop event
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # Start servers
    server_task = asyncio.create_task(server.serve())
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

    # Cleanup pidfile and socket
    remove_pidfile(pf)
    cleanup_stale_socket(repo_root)
    logger.info("Daemon shut down cleanly")
