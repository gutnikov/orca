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

from orca.daemon.lifecycle import read_browser_port
from orca.daemon.manager import RunManager, RunStatus, debug_review_url


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
            "browser_port": read_browser_port(manager.repo_root),
            "repo_root": str(manager.repo_root),
        }
    )


async def _list_runs(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    runs = manager.list_runs()
    browser_port = read_browser_port(manager.repo_root)
    return JSONResponse([r.to_summary(browser_port=browser_port) for r in runs])


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

    raw_overrides = body.get("worker_overrides")
    worker_overrides: dict[str, dict[str, str]] | None = None
    if raw_overrides is not None:
        if not isinstance(raw_overrides, dict):
            return JSONResponse({"error": "worker_overrides must be an object"}, status_code=400)
        worker_overrides = {}
        for state_name, fields in raw_overrides.items():
            if not isinstance(fields, dict):
                return JSONResponse(
                    {"error": f"worker_overrides[{state_name!r}] must be an object"},
                    status_code=400,
                )
            worker_overrides[str(state_name)] = {str(k): str(v) for k, v in fields.items()}

    try:
        run_id = await manager.start_run(
            task_file=task_file,
            workflow=body.get("workflow"),
            branch=body.get("branch"),
            base=body.get("base"),
            run_id=body.get("run_id"),
            max_hops=body.get("max_hops"),
            max_retries=body.get("max_retries"),
            insights=bool(body.get("insights", False)),
            debug=bool(body.get("debug", False)),
            worker_overrides=worker_overrides,
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
    browser_port = read_browser_port(manager.repo_root)
    if compact:
        result = _compact_run(run_id, state, run_info, manager.get_sessions(run_id), browser_port)
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
    browser_port: int | None,
) -> dict[str, Any]:
    """Build a compact run summary, stripping event_log, fields, and completed sessions.

    For any issue currently in `debug_pending`, attaches `debug_review_url` so
    polling agents can surface the URL to the user without having to scan the
    event log themselves.
    """
    compact_issues: dict[str, Any] = {}
    debug_reviews: list[dict[str, Any]] = []
    for iid, issue in state.get("issues", {}).items():
        compact_issue: dict[str, Any] = {
            "title": issue.get("fields", {}).get("title", ""),
            "state": issue["state"],
            "worker_active": issue["worker_active"],
            "failure_count": issue.get("failure_count", 0),
            "hop_count": issue.get("hop_count", 0),
            "visit_counts": issue.get("visit_counts", {}),
        }
        if issue.get("debug_pending"):
            url = debug_review_url(browser_port, run_id, iid)
            if url is not None:
                compact_issue["debug_review_url"] = url
                debug_reviews.append({"issue_id": iid, "state": issue["state"], "url": url})
            else:
                compact_issue["debug_review_url"] = None
                debug_reviews.append({"issue_id": iid, "state": issue["state"]})
        if issue.get("modify_pending"):
            compact_issue["modify_pending"] = True
        compact_issues[iid] = compact_issue
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
        "debug_reviews": debug_reviews,
    }
    # If any issue is paused for debug review, populate the must_surface_to_user
    # field with the verbatim text the agent should output. This is the strongest
    # signal we can give a polling agent: a top-level field name that is
    # impossible to read past, with the exact words the user should see.
    if debug_reviews:
        lines = ["⏸ Paused for debug review:"]
        for r in debug_reviews:
            url = r.get("url") or "(daemon browser port unavailable)"
            lines.append(f"  state `{r.get('state', '?')}` → {url}")
        lines.append("")
        lines.append(
            "Output the above to the user verbatim and end your turn. Do NOT narrate "
            "the worker's result, the routing decision, or what would happen next — "
            "the browser UI shows all of that. Wait for the user's next message."
        )
        result["must_surface_to_user"] = "\n".join(lines)
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


async def _get_debug_review(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    snapshot = manager.get_debug_review(run_id, issue_id)
    if snapshot is None:
        return JSONResponse({"error": "not_pending"}, status_code=404)
    return JSONResponse(snapshot)


async def _post_debug_decide(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    action = body.get("action")
    comments = body.get("comments", [])
    if action not in ("accept", "restart", "modify_restart", "modify_continue", "stop"):
        return JSONResponse({"error": f"invalid action: {action!r}"}, status_code=400)

    try:
        manager.submit_debug_decision(run_id, issue_id, action, comments)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            return JSONResponse({"error": msg}, status_code=404)
        if "already_decided" in msg:
            return JSONResponse({"error": msg}, status_code=409)
        if "run_stopped" in msg:
            return JSONResponse({"error": msg}, status_code=410)
        return JSONResponse({"error": msg}, status_code=400)

    return JSONResponse({"accepted": True})


async def _post_restart_state(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    try:
        await manager.restart_state(run_id, issue_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "restarted"})


async def _post_clear_modify_pending(request: Request) -> JSONResponse:
    """Clear modify_pending after a modify_continue rewrite is done."""
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    try:
        manager.clear_modify_pending(run_id, issue_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"status": "ok"})


async def _post_debug_question(request: Request) -> JSONResponse:
    """Flag a review comment as a question the agent should answer."""
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    client_comment_id = body.get("client_comment_id")
    file = body.get("file")
    line = body.get("line")
    comment_body = body.get("body")
    if not isinstance(client_comment_id, str) or not client_comment_id:
        return JSONResponse({"error": "client_comment_id required"}, status_code=400)
    if not isinstance(file, str) or not isinstance(comment_body, str):
        return JSONResponse({"error": "file and body required"}, status_code=400)

    try:
        question_id = manager.ask_debug_question(
            run_id,
            issue_id,
            client_comment_id,
            file,
            line if isinstance(line, int) else None,
            comment_body,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"question_id": question_id, "answer": None})


async def _get_debug_questions(request: Request) -> JSONResponse:
    """List all questions (answered + unanswered) for the current debug pause."""
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    try:
        questions = manager.list_debug_questions(run_id, issue_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"questions": questions})


async def _post_debug_answer(request: Request) -> JSONResponse:
    """Agent posts an answer to a previously-asked question. Called via MCP."""
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    question_id: str = request.path_params["question_id"]
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    answer = body.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return JSONResponse({"error": "answer required (non-empty string)"}, status_code=400)
    try:
        manager.answer_debug_question(run_id, issue_id, question_id, answer)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"status": "ok"})


def _api_routes() -> list[Route]:
    return [
        Route("/api/status", _status, methods=["GET"]),
        Route("/api/runs", _list_runs, methods=["GET"]),
        Route("/api/runs/start", _start_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug", _get_debug_review, methods=["GET"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug/decide", _post_debug_decide, methods=["POST"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug/restart", _post_restart_state, methods=["POST"]),
        Route(
            "/api/runs/{run_id:path}/issues/{issue_id}/debug/clear-modify-pending",
            _post_clear_modify_pending,
            methods=["POST"],
        ),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug/questions", _post_debug_question, methods=["POST"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug/questions", _get_debug_questions, methods=["GET"]),
        Route(
            "/api/runs/{run_id:path}/issues/{issue_id}/debug/questions/{question_id}/answer",
            _post_debug_answer,
            methods=["POST"],
        ),
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
        Route("/api/runs/{run_id:path}", _get_run, methods=["GET"]),
    ]


def create_app(manager: RunManager) -> Starlette:
    """Full daemon HTTP API — UDS-only privileged surface."""
    app = Starlette(routes=_api_routes())
    app.state.manager = manager
    app.state.start_time = time.monotonic()
    return app


class _SPAStaticFiles(StaticFiles):  # type: ignore[misc,unused-ignore]
    """StaticFiles that falls back to index.html for SPA client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404:
                return FileResponse(Path(str(self.directory)) / "index.html")
            raise


def _web_dist_dir() -> Path:
    """Locate the built web bundle.

    Lookup order:

    1. **Wheel-bundled location** (`<site-packages>/orca/web_dist/`) — what
       pipx-installed users get. The wheel ships a prebuilt bundle via
       `force-include` in `pyproject.toml`.
    2. **Repo source location** (`<repo>/web/dist/`) — what orca devs get
       when running from a source checkout after `pnpm build`.
    3. **Dev-only stub** — only reached when running from a source checkout
       *and* the dev hasn't built the bundle. Tells them to run
       `pnpm build` or `pnpm dev`. End users should never see this because
       the wheel includes `web_dist/` unconditionally.
    """
    pkg_root = Path(__file__).resolve().parents[1]  # .../orca/daemon -> .../orca
    bundled = pkg_root / "web_dist"
    if bundled.exists():
        return bundled
    repo_root = pkg_root.parent.parent  # .../src/orca -> .../src -> repo root
    dev_dist = repo_root / "web" / "dist"
    if dev_dist.exists():
        return dev_dist
    stub = repo_root / "web" / "_dist_stub"
    stub.mkdir(parents=True, exist_ok=True)
    index = stub / "index.html"
    if not index.exists():
        index.write_text(
            '<!doctype html><html><body style="font-family:system-ui;padding:2rem;max-width:40rem">'
            "<h1>Orca web bundle missing</h1>"
            "<p>You are running orca from a source checkout and the web "
            "bundle hasn't been built yet.</p>"
            "<p>For development, run <code>cd web &amp;&amp; pnpm dev</code> "
            'and open <a href="http://localhost:5174">http://localhost:5174</a> '
            "(the Vite dev server proxies <code>/api</code> back to this "
            "daemon).</p>"
            "<p>For a one-shot build, run <code>cd web &amp;&amp; pnpm build</code> "
            "and reload this page.</p>"
            "<p><em>If you installed orca via pipx and you're seeing this, "
            "the wheel was built without the web bundle — please "
            "re-install or report the bug.</em></p>"
            "</body></html>"
        )
    return stub


def create_browser_app(manager: RunManager) -> Starlette:
    """Browser-facing app: SPA static assets + API routes for same-origin fetches."""
    routes: list[Any] = [
        *_api_routes(),
        Mount("/", app=_SPAStaticFiles(directory=str(_web_dist_dir()), html=True), name="web"),
    ]

    app = Starlette(routes=routes)
    app.state.manager = manager
    app.state.start_time = time.monotonic()
    return app
