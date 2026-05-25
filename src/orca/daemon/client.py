"""HTTP client that proxies to the orca daemon over its Unix socket."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp


class DaemonClient:
    """Proxy to the orca daemon HTTP API via Unix socket."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path

    def _connector(self) -> aiohttp.UnixConnector:
        return aiohttp.UnixConnector(path=str(self._socket_path))

    async def _get_json(self, path: str) -> dict[str, Any]:
        async with (
            aiohttp.ClientSession(connector=self._connector()) as session,
            session.get(f"http://localhost{path}") as resp,
        ):
            return await resp.json()  # type: ignore[no-any-return]

    async def _get_text(self, path: str) -> str:
        async with (
            aiohttp.ClientSession(connector=self._connector()) as session,
            session.get(f"http://localhost{path}") as resp,
        ):
            text: str = await resp.text()
            return text

    async def _post_json(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        async with (
            aiohttp.ClientSession(connector=self._connector()) as session,
            session.post(f"http://localhost{path}", json=body) as resp,
        ):
            return await resp.json()  # type: ignore[no-any-return]

    async def _put_json(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        async with (
            aiohttp.ClientSession(connector=self._connector()) as session,
            session.put(f"http://localhost{path}", json=body) as resp,
        ):
            return await resp.json()  # type: ignore[no-any-return]

    async def _delete_json(self, path: str) -> dict[str, Any]:
        async with (
            aiohttp.ClientSession(connector=self._connector()) as session,
            session.delete(f"http://localhost{path}") as resp,
        ):
            return await resp.json()  # type: ignore[no-any-return]

    async def status(self) -> dict[str, Any]:
        return await self._get_json("/api/status")

    async def list_runs(self) -> list[dict[str, Any]]:
        return await self._get_json("/api/runs")  # type: ignore[return-value]

    async def get_run(self, run_id: str, *, compact: bool = False) -> dict[str, Any]:
        path = f"/api/runs/{run_id}"
        if compact:
            path += "?compact=true"
        return await self._get_json(path)

    async def get_issue(self, run_id: str, issue_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/runs/{run_id}/issues/{issue_id}")

    async def get_worker_log(self, run_id: str, issue_id: str, tail: int = 100) -> str:
        return await self._get_text(f"/api/runs/{run_id}/logs/{issue_id}?tail={tail}")

    async def start_run(
        self,
        task_file: str,
        workflow: str | None = None,
        branch: str | None = None,
        run_id: str | None = None,
        debug: bool = False,
        worker_overrides: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "task_file": task_file,
            "workflow": workflow,
            "branch": branch,
            "run_id": run_id,
            "debug": debug,
        }
        if worker_overrides:
            body["worker_overrides"] = worker_overrides
        return await self._post_json("/api/runs/start", body)

    async def stop_run(self, run_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/stop")

    async def drop_run(self, run_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/drop")

    async def resume_run(self, run_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/resume")

    async def retry_issue(self, run_id: str, issue_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/retry/{issue_id}")

    async def unblock_worker(self, run_id: str, issue_id: str, message: str) -> dict[str, Any]:
        return await self._post_json(
            f"/api/runs/{run_id}/unblock/{issue_id}",
            {"message": message},
        )

    async def get_debug_review(self, run_id: str, issue_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/runs/{run_id}/issues/{issue_id}/debug")

    async def submit_debug_decision(
        self,
        run_id: str,
        issue_id: str,
        action: str,
    ) -> dict[str, Any]:
        # Comments are no longer sent on the wire — the daemon persists them
        # as the user authors them (Task 7) and the reducer bundles them
        # into the decision payload from the persisted state.
        return await self._post_json(
            f"/api/runs/{run_id}/issues/{issue_id}/debug/decide",
            {"action": action},
        )

    async def restart_state(self, run_id: str, issue_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/issues/{issue_id}/debug/restart")

    async def clear_modify_pending(self, run_id: str, issue_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/issues/{issue_id}/debug/clear-modify-pending")

    # ------------------------------------------------------------------ #
    # Inline comments + comment threads                                  #
    # ------------------------------------------------------------------ #

    async def list_inline_comments(self, run_id: str, issue_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/runs/{run_id}/issues/{issue_id}/comments")

    async def save_inline_comment(
        self,
        run_id: str,
        issue_id: str,
        comment_id: str,
        file: str,
        line: int | None,
        body: str,
    ) -> dict[str, Any]:
        return await self._put_json(
            f"/api/runs/{run_id}/issues/{issue_id}/comments/{comment_id}",
            {"file": file, "line": line, "body": body},
        )

    async def delete_inline_comment(self, run_id: str, issue_id: str, comment_id: str) -> dict[str, Any]:
        return await self._delete_json(f"/api/runs/{run_id}/issues/{issue_id}/comments/{comment_id}")

    async def add_thread_message(
        self,
        run_id: str,
        issue_id: str,
        comment_id: str,
        role: str,
        body: str,
    ) -> dict[str, Any]:
        return await self._post_json(
            f"/api/runs/{run_id}/issues/{issue_id}/comments/{comment_id}/messages",
            {"role": role, "body": body},
        )

    async def skip_comment(self, run_id: str, issue_id: str, comment_id: str, reason: str) -> dict[str, Any]:
        return await self._post_json(
            f"/api/runs/{run_id}/issues/{issue_id}/comments/{comment_id}/skip",
            {"reason": reason},
        )
