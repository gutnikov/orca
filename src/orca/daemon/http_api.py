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


def _get_version() -> str:
    from importlib.metadata import version

    try:
        return version("orca")
    except Exception:
        return "dev"


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
            "version": _get_version(),
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
    # If any issue is paused for debug review AND we haven't yet shown the URL
    # to the agent for this pause, populate must_surface_to_user. Once the agent
    # has surfaced the URL on its first poll, we suppress this field on
    # subsequent polls so the agent stays in its polling loop and can engage
    # with inline comments / detect resolution. agent_surfaced_at is reset to
    # None whenever a new debug_pending begins (see reducer._handle_worker_result).
    live_issues = (
        run_info.orchestrator.state.issues if run_info is not None and run_info.orchestrator is not None else {}
    )
    unsurfaced_reviews = [
        r
        for r in debug_reviews
        if (live := live_issues.get(r["issue_id"])) is not None and live.agent_surfaced_at is None
    ]
    if unsurfaced_reviews:
        lines = ["⏸ Paused for debug review:"]
        for r in unsurfaced_reviews:
            url = r.get("url") or "(daemon browser port unavailable)"
            lines.append(f"  state `{r.get('state', '?')}` → {url}")
        lines.append("")
        lines.append(
            "Output the above to the user verbatim, then continue polling silently. "
            "Do NOT end your turn and do NOT narrate the worker's result, routing "
            "decision, or next steps — the browser UI shows all of that. This field "
            "appears only once per pause; on subsequent polls keep watching for "
            "`debug_reviews` to empty (user picked an action) and call "
            "`orca_list_pending_comments` to engage with inline-comment threads."
        )
        result["must_surface_to_user"] = "\n".join(lines)
        ts = time.time()
        for r in unsurfaced_reviews:
            live = live_issues.get(r["issue_id"])
            if live is not None:
                live.agent_surfaced_at = ts
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


async def _get_worker_log(request: Request) -> PlainTextResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    tail = int(request.query_params.get("tail", "100"))
    session_id = request.query_params.get("session_id")
    text = manager.get_worker_log(run_id, issue_id, tail, session_id=session_id)
    return PlainTextResponse(text)


async def _get_all_worker_logs(request: Request) -> PlainTextResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    tail = int(request.query_params.get("tail", "100"))
    text = manager.get_all_worker_logs(run_id, tail)
    return PlainTextResponse(text)


async def _get_session_prompt(request: Request) -> PlainTextResponse | JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    session_id: str = request.path_params["session_id"]
    text = manager.get_session_prompt(run_id, session_id)
    if text is None:
        return JSONResponse({"error": f"prompt for session '{session_id}' not found"}, status_code=404)
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
    attempt_raw = request.query_params.get("attempt")
    attempt: int | None
    if attempt_raw is None:
        attempt = None
    else:
        try:
            attempt = int(attempt_raw)
        except ValueError:
            return JSONResponse({"error": "invalid attempt"}, status_code=400)
    snapshot = manager.get_debug_review(run_id, issue_id, attempt=attempt)
    if snapshot is None:
        # Preserve "not_pending" for the live-mode contract (orca-prompt-config-rewrite
        # playbook branches on it). Use "not_found" only for past-mode misses.
        error = "not_found" if attempt is not None else "not_pending"
        return JSONResponse({"error": error}, status_code=404)
    return JSONResponse(snapshot)


async def _get_debug_attempts(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    attempts = manager.list_debug_attempts(run_id, issue_id)
    return JSONResponse(attempts)


async def _post_debug_decide(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    action = body.get("action")
    # Note: `comments` is no longer read from the request body — the daemon
    # persists comments as the user authors them (Task 7) and the reducer
    # bundles them into the decision payload from `Issue.inline_comments`.
    if action not in ("accept", "restart", "modify_restart", "modify_continue", "stop"):
        return JSONResponse({"error": f"invalid action: {action!r}"}, status_code=400)

    try:
        manager.submit_debug_decision(run_id, issue_id, action)
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


async def _get_inline_comments(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    try:
        comments = manager.list_inline_comments_with_threads(run_id, issue_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"comments": comments})


async def _put_inline_comment(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    comment_id: str = request.path_params["comment_id"]
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    file = body.get("file")
    line = body.get("line")
    comment_body = body.get("body")
    if not isinstance(file, str) or not isinstance(comment_body, str):
        return JSONResponse({"error": "file and body required"}, status_code=400)
    line_val: int | None = line if isinstance(line, int) and not isinstance(line, bool) else None
    try:
        manager.save_inline_comment(run_id, issue_id, comment_id, file, line_val, comment_body)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"ok": True})


async def _delete_inline_comment(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    comment_id: str = request.path_params["comment_id"]
    try:
        manager.delete_inline_comment(run_id, issue_id, comment_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"ok": True})


async def _post_thread_message(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    comment_id: str = request.path_params["comment_id"]
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    role = body.get("role")
    msg_body = body.get("body")
    if role not in ("user", "agent"):
        return JSONResponse({"error": "role must be 'user' or 'agent'"}, status_code=400)
    if not isinstance(msg_body, str) or not msg_body.strip():
        return JSONResponse({"error": "body required (non-empty string)"}, status_code=400)
    try:
        message_id = manager.add_thread_message(run_id, issue_id, comment_id, role, msg_body)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"message_id": message_id})


async def _post_thread_skip(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    comment_id: str = request.path_params["comment_id"]
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        body = {}
    raw_reason = body.get("reason", "") if isinstance(body, dict) else ""
    reason = raw_reason if isinstance(raw_reason, str) else ""
    try:
        manager.skip_comment(run_id, issue_id, comment_id, reason)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"ok": True})


def _api_routes() -> list[Route]:
    return [
        Route("/api/status", _status, methods=["GET"]),
        Route("/api/runs", _list_runs, methods=["GET"]),
        Route("/api/runs/start", _start_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug", _get_debug_review, methods=["GET"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug/attempts", _get_debug_attempts, methods=["GET"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug/decide", _post_debug_decide, methods=["POST"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}/debug/restart", _post_restart_state, methods=["POST"]),
        Route(
            "/api/runs/{run_id:path}/issues/{issue_id}/debug/clear-modify-pending",
            _post_clear_modify_pending,
            methods=["POST"],
        ),
        Route(
            "/api/runs/{run_id:path}/issues/{issue_id}/comments",
            _get_inline_comments,
            methods=["GET"],
        ),
        Route(
            "/api/runs/{run_id:path}/issues/{issue_id}/comments/{comment_id}",
            _put_inline_comment,
            methods=["PUT"],
        ),
        Route(
            "/api/runs/{run_id:path}/issues/{issue_id}/comments/{comment_id}",
            _delete_inline_comment,
            methods=["DELETE"],
        ),
        Route(
            "/api/runs/{run_id:path}/issues/{issue_id}/comments/{comment_id}/messages",
            _post_thread_message,
            methods=["POST"],
        ),
        Route(
            "/api/runs/{run_id:path}/issues/{issue_id}/comments/{comment_id}/skip",
            _post_thread_skip,
            methods=["POST"],
        ),
        Route("/api/runs/{run_id:path}/issues/{issue_id}", _get_issue, methods=["GET"]),
        Route("/api/runs/{run_id:path}/logs/{issue_id}", _get_worker_log, methods=["GET"]),
        Route("/api/runs/{run_id:path}/logs", _get_all_worker_logs, methods=["GET"]),
        Route("/api/runs/{run_id:path}/sessions/{session_id}/prompt", _get_session_prompt, methods=["GET"]),
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
