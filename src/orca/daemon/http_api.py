"""Starlette HTTP API for the orca daemon."""

from __future__ import annotations

import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from orca.daemon.manager import RunManager, RunStatus


async def _status(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    start_time: float = request.app.state.start_time
    runs = manager.list_runs()
    active = sum(1 for r in runs if r.status == RunStatus.RUNNING)
    return JSONResponse(
        {
            "uptime": time.monotonic() - start_time,
            "active_runs": active,
            "total_runs": len(runs),
        }
    )


async def _list_runs(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    runs = manager.list_runs()
    return JSONResponse([r.to_summary() for r in runs])


async def _start_run(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    task_file_str = body.get("task_file")
    if not task_file_str:
        return JSONResponse({"error": "task_file is required"}, status_code=400)

    from pathlib import Path

    task_file = Path(task_file_str)
    if not task_file.is_absolute():
        task_file = manager.repo_root / task_file

    try:
        run_id = await manager.start_run(
            task_file=task_file,
            workflow=body.get("workflow"),
            branch=body.get("branch"),
            base=body.get("base"),
            max_hops=body.get("max_hops"),
            max_retries=body.get("max_retries"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse({"run_id": run_id}, status_code=201)


async def _get_run(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    state = manager.get_run_state(run_id)
    if state is None:
        return JSONResponse({"error": f"run '{run_id}' not found"}, status_code=404)
    run_info = manager.get_run(run_id)
    result: dict[str, Any] = {"run_id": run_id, "state": state}
    if run_info is not None:
        result["status"] = run_info.status.value
    return JSONResponse(result)


async def _get_issue(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    issue = manager.get_issue(run_id, issue_id)
    if issue is None:
        return JSONResponse({"error": f"issue '{issue_id}' not found in run '{run_id}'"}, status_code=404)
    return JSONResponse(issue)


async def _get_insights(request: Request) -> PlainTextResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    text = manager.get_insights(run_id)
    return PlainTextResponse(text)


async def _get_worker_log(request: Request) -> PlainTextResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    tracking_id: str = request.path_params["tracking_id"]
    tail = int(request.query_params.get("tail", "100"))
    text = manager.get_worker_log(run_id, tracking_id, tail)
    return PlainTextResponse(text)


async def _stop_run(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    run_info = manager.get_run(run_id)
    if run_info is None:
        return JSONResponse({"error": f"run '{run_id}' not found"}, status_code=404)
    await manager.stop_run(run_id)
    return JSONResponse({"status": "stopped"})


async def _retry_issue(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    run_info = manager.get_run(run_id)
    if run_info is None:
        return JSONResponse({"error": f"run '{run_id}' not found"}, status_code=404)
    try:
        manager.retry_issue(run_id, issue_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"status": "retry requested"})


async def _hot_session(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    run_info = manager.get_run(run_id)
    if run_info is None:
        return JSONResponse({"error": f"run '{run_id}' not found"}, status_code=404)
    if run_info.orchestrator is None:
        return JSONResponse({"error": f"run '{run_id}' has no orchestrator"}, status_code=400)

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    session_id = body.get("session_id")
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    hot: bool = body.get("hot", True)
    if hot:
        run_info.orchestrator.set_hot_session(session_id)
    else:
        run_info.orchestrator.set_cold_session(session_id)

    return JSONResponse({"status": "ok"})


def create_app(manager: RunManager) -> Starlette:
    """Create the daemon HTTP API application."""
    routes = [
        Route("/api/status", _status, methods=["GET"]),
        Route("/api/runs", _list_runs, methods=["GET"]),
        Route("/api/runs/start", _start_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}", _get_issue, methods=["GET"]),
        Route("/api/runs/{run_id:path}/insights", _get_insights, methods=["GET"]),
        Route("/api/runs/{run_id:path}/logs/{tracking_id}", _get_worker_log, methods=["GET"]),
        Route("/api/runs/{run_id:path}/stop", _stop_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/retry/{issue_id}", _retry_issue, methods=["POST"]),
        Route("/api/runs/{run_id:path}/hot-session", _hot_session, methods=["POST"]),
        Route("/api/runs/{run_id:path}", _get_run, methods=["GET"]),
    ]

    app = Starlette(routes=routes)
    app.state.manager = manager
    app.state.start_time = time.monotonic()
    return app
