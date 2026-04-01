"""Daemon entry point: start the HTTP server on a Unix domain socket."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

import uvicorn

from orca.daemon.http_api import create_app
from orca.daemon.lifecycle import (
    DaemonAlreadyRunningError,
    check_daemon_running,
    cleanup_stale_socket,
    pidfile_path,
    remove_pidfile,
    socket_path,
    write_pidfile,
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

    # 5. Configure uvicorn
    config = uvicorn.Config(
        app=app,
        uds=str(sock),
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # 6. Set up signal handlers with a stop event
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # Start server in a task
    server_task = asyncio.create_task(server.serve())

    # Wait for stop signal
    await stop_event.wait()

    # 7. Graceful shutdown
    logger.info("Stopping all runs...")
    await manager.stop_all()

    server.should_exit = True
    await server_task

    # Cleanup pidfile and socket
    remove_pidfile(pf)
    cleanup_stale_socket(repo_root)
    logger.info("Daemon shut down cleanly")
