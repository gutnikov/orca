"""Starlette HTTP API for the orca daemon."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from orca.daemon.explanations import ExplanationCorruptedError, read_explanation
from orca.daemon.form_validator import validate_submission
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
            run_id=body.get("run_id"),
            max_hops=body.get("max_hops"),
            max_retries=body.get("max_retries"),
            state_ref=body.get("state_ref"),
            insights=bool(body.get("insights", False)),
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse({"run_id": run_id}, status_code=201)


async def _get_run(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    compact = request.query_params.get("compact") == "true"
    state = manager.get_run_state(run_id)
    if state is None:
        return JSONResponse({"error": f"run '{run_id}' not found"}, status_code=404)
    run_info = manager.get_run(run_id)
    if compact:
        result = _compact_run(run_id, state, run_info, manager.get_sessions(run_id))
    else:
        sessions = manager.get_sessions(run_id)
        result = {"run_id": run_id, "state": state, "sessions": sessions}
        if run_info is not None:
            result["status"] = run_info.status.value
    return JSONResponse(result)


def _compact_run(
    run_id: str,
    state: dict[str, Any],
    run_info: Any,
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a compact run summary, stripping event_log, fields, and completed sessions."""
    compact_issues: dict[str, Any] = {}
    for iid, issue in state.get("issues", {}).items():
        compact_issues[iid] = {
            "title": issue.get("fields", {}).get("title", ""),
            "state": issue["state"],
            "worker_active": issue["worker_active"],
            "failure_count": issue.get("failure_count", 0),
            "hop_count": issue.get("hop_count", 0),
            "visit_counts": issue.get("visit_counts", {}),
        }
    # Keep only the latest active session per issue (or the most recent completed one)
    latest_sessions: dict[str, dict[str, Any]] = {}
    for s in sessions:
        iid = s.get("issue_id", "")
        keep = {
            "state": s.get("state"),
            "progress": s.get("progress"),
            "status": s.get("status"),
            "progress_updated_at": s.get("progress_updated_at"),
        }
        if s.get("completed_at") is None or iid not in latest_sessions:
            latest_sessions[iid] = keep
    result: dict[str, Any] = {
        "run_id": run_id,
        "issues": compact_issues,
        "sessions": latest_sessions,
    }
    if run_info is not None:
        result["status"] = run_info.status.value
    return result


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
    issue_id: str = request.path_params["issue_id"]
    tail = int(request.query_params.get("tail", "100"))
    text = manager.get_worker_log(run_id, issue_id, tail)
    return PlainTextResponse(text)


async def _get_all_worker_logs(request: Request) -> PlainTextResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    tail = int(request.query_params.get("tail", "100"))
    text = manager.get_all_worker_logs(run_id, tail)
    return PlainTextResponse(text)


async def _stop_run(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    run_info = manager.get_run(run_id)
    if run_info is None:
        return JSONResponse({"error": f"run '{run_id}' not found"}, status_code=404)
    await manager.stop_run(run_id)
    return JSONResponse({"status": "stopped"})


async def _drop_run(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    try:
        await manager.drop_run(run_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"status": "dropped"})


async def _resume_run(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    try:
        await manager.resume_run(run_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "resumed"})


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


async def _unblock_worker(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    message = body.get("message")
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    try:
        manager.unblock_worker(run_id, issue_id, message)
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg else 400
        return JSONResponse({"error": error_msg}, status_code=status)

    return JSONResponse({"status": "ok"})


async def _get_form(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]

    info = manager.get_pending_form(run_id, issue_id)
    if info is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if info["submitted_at"] is not None:
        return JSONResponse(
            {"error": "already_submitted", "submitted_at": info["submitted_at"]},
            status_code=410,
        )
    return JSONResponse(
        {
            "run_id": run_id,
            "issue_id": issue_id,
            "schema": info["schema"],
            "context": {
                "state": info["state"],
                "reason": info["reason"],
                "started_waiting_at": info["started_waiting_at"],
            },
        }
    )


async def _submit_form(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    cancelled = body.get("cancelled") is True
    values = body.get("values")
    if not cancelled and not isinstance(values, dict):
        return JSONResponse({"error": "values must be an object, or set cancelled=true"}, status_code=400)

    info = manager.get_pending_form(run_id, issue_id)
    if info is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if info["submitted_at"] is not None:
        return JSONResponse({"error": "already_submitted"}, status_code=410)

    schema = info["schema"]
    if not cancelled:
        field_errors = validate_submission(schema, values or {})
        if field_errors:
            return JSONResponse(
                {"error": "validation_failed", "field_errors": field_errors},
                status_code=422,
            )

    envelope: dict[str, Any] = (
        {"submitted": False, "cancelled": True} if cancelled else {"submitted": True, "values": values}
    )

    result = manager.submit_form(run_id, issue_id, envelope)
    if result == "not_found":
        return JSONResponse({"error": "not_found"}, status_code=404)
    if result == "gone":
        return JSONResponse({"error": "already_submitted"}, status_code=410)
    if result == "not_waiting":
        return JSONResponse({"error": "worker_not_waiting"}, status_code=409)

    return JSONResponse({"ok": True})


async def _list_pending_forms(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    return JSONResponse({"pending": manager.list_pending_forms()})


async def _get_explanation(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    flow: str = request.path_params["flow"]
    lang: str = request.query_params.get("lang", "en")

    try:
        payload = read_explanation(manager.repo_root, flow, lang)
    except ExplanationCorruptedError as exc:
        return JSONResponse(
            {"error": "corrupted", "detail": str(exc)},
            status_code=500,
        )

    if payload is None:
        return JSONResponse(
            {
                "error": "not_found",
                "hint": (
                    f"No explanation cached for flow '{flow}' in language '{lang}'. "
                    "Generate it by running the orca-workflow-explain playbook."
                ),
            },
            status_code=404,
        )
    return JSONResponse(payload)


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


def _form_routes() -> list[Route]:
    """Browser-facing routes — safe to expose on TCP."""
    return [
        Route("/api/runs/{run_id:path}/forms/{issue_id}", _get_form, methods=["GET"]),
        Route("/api/runs/{run_id:path}/forms/{issue_id}/submit", _submit_form, methods=["POST"]),
        Route("/api/forms/pending", _list_pending_forms, methods=["GET"]),
        Route("/api/explanations/{flow}", _get_explanation, methods=["GET"]),
    ]


def create_app(manager: RunManager) -> Starlette:
    """Full daemon HTTP API — UDS-only privileged surface."""
    routes = [
        Route("/api/status", _status, methods=["GET"]),
        Route("/api/runs", _list_runs, methods=["GET"]),
        Route("/api/runs/start", _start_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}", _get_issue, methods=["GET"]),
        Route("/api/runs/{run_id:path}/insights", _get_insights, methods=["GET"]),
        Route("/api/runs/{run_id:path}/logs/{issue_id}", _get_worker_log, methods=["GET"]),
        Route("/api/runs/{run_id:path}/logs", _get_all_worker_logs, methods=["GET"]),
        Route("/api/runs/{run_id:path}/stop", _stop_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/resume", _resume_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/drop", _drop_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/retry/{issue_id}", _retry_issue, methods=["POST"]),
        Route("/api/runs/{run_id:path}/unblock/{issue_id}", _unblock_worker, methods=["POST"]),
        Route("/api/runs/{run_id:path}/hot-session", _hot_session, methods=["POST"]),
        *_form_routes(),
        Route("/api/runs/{run_id:path}", _get_run, methods=["GET"]),
    ]

    app = Starlette(routes=routes)
    app.state.manager = manager
    app.state.start_time = time.monotonic()
    return app


class _SPAStaticFiles(StaticFiles):  # type: ignore[misc]
    """StaticFiles that falls back to index.html for SPA client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404:
                return FileResponse(Path(str(self.directory)) / "index.html")
            raise


def _web_dist_dir() -> Path:
    """Return web/dist/ relative to the orca source tree, falling back to a
    sibling 'web/_dist_stub' directory so test/dev startup doesn't blow up
    when the production bundle hasn't been built."""
    src_root = Path(__file__).resolve().parents[2]  # .../src/orca/daemon -> .../src
    candidate = src_root.parent / "web" / "dist"
    if candidate.exists():
        return candidate
    stub = src_root.parent / "web" / "_dist_stub"
    stub.mkdir(parents=True, exist_ok=True)
    index = stub / "index.html"
    if not index.exists():
        index.write_text(
            "<!doctype html><html><body><h1>Orca web</h1>"
            "<p>The web bundle has not been built yet. "
            "Run <code>cd web &amp;&amp; pnpm build</code>, or "
            "use the Vite dev server at <code>http://localhost:5174</code>.</p>"
            "</body></html>"
        )
    return stub


def create_browser_app(manager: RunManager) -> Starlette:
    """Browser-facing app: form endpoints + SPA static assets only.

    The full privileged surface (start/stop/unblock/etc.) is intentionally
    absent — those stay UDS-only. Mounted on a localhost TCP listener.
    """
    routes: list[Any] = list(_form_routes())
    routes.append(Mount("/", app=_SPAStaticFiles(directory=str(_web_dist_dir()), html=True), name="web"))

    app = Starlette(routes=routes)
    app.state.manager = manager
    app.state.start_time = time.monotonic()
    return app
