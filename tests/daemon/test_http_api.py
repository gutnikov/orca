from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from orca.daemon.http_api import create_app
from orca.daemon.manager import RunManager


@pytest.fixture()
def manager(tmp_path: Path) -> RunManager:
    return RunManager(tmp_path)


@pytest.fixture()
def client(manager: RunManager) -> TestClient:
    app = create_app(manager)
    return TestClient(app)


class TestStatusEndpoint:
    def test_status(self, client: TestClient) -> None:
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "uptime" in data
        assert data["active_runs"] == 0
        assert "total_runs" in data


class TestListRuns:
    def test_empty(self, client: TestClient) -> None:
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetRun:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default")
        assert resp.status_code == 404


class TestGetIssue:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default/issues/abc")
        assert resp.status_code == 404


class TestWorkerLog:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default/logs/tid-1")
        assert resp.status_code == 200
        assert resp.text == ""


class TestWorkerLogTailParam:
    """?tail= must be parsed defensively: non-integer input falls back to the
    default, and values are clamped to [1, 10000] so negative numbers can't
    corrupt the tail slice."""

    def test_non_integer_tail_returns_200_not_500(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default/logs/issue-1", params={"tail": "abc"})
        assert resp.status_code == 200
        assert resp.text == ""

    def test_non_integer_tail_all_logs_returns_200_not_500(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default/logs", params={"tail": "abc"})
        assert resp.status_code == 200

    def test_tail_values_sanitized(self, manager: RunManager, client: TestClient) -> None:
        captured: list[int] = []

        def fake_get_worker_log(
            run_id: str,
            issue_id: str,
            tail: int = 100,
            session_id: str | None = None,
        ) -> str:
            captured.append(tail)
            return ""

        manager.get_worker_log = fake_get_worker_log  # type: ignore[method-assign]
        for raw, expected in (("abc", 100), ("-5", 1), ("0", 1), ("50", 50), ("999999", 10000)):
            client.get("/api/runs/x:default/logs/issue-1", params={"tail": raw})
            assert captured[-1] == expected

    def test_tail_values_sanitized_all_logs(self, manager: RunManager, client: TestClient) -> None:
        captured: list[int] = []

        def fake_get_all_worker_logs(run_id: str, tail: int = 100) -> str:
            captured.append(tail)
            return ""

        manager.get_all_worker_logs = fake_get_all_worker_logs  # type: ignore[method-assign]
        for raw, expected in (("abc", 100), ("-5", 1), ("999999", 10000)):
            client.get("/api/runs/x:default/logs", params={"tail": raw})
            assert captured[-1] == expected


class TestWorkerLogBySession:
    """Per-session log resolution via ?session_id=... (used by web dashboard)."""

    def test_session_id_param_accepted(self, client: TestClient) -> None:
        # Unknown run still returns 200 with empty body — same contract as
        # the existing ?tail= behavior. We're only verifying the param is
        # accepted (no 400), not the resolution path (covered by manager tests).
        resp = client.get(
            "/api/runs/nonexistent:default/logs/issue-1",
            params={"session_id": "sess-abc"},
        )
        assert resp.status_code == 200
        assert resp.text == ""

    def test_session_id_and_tail_combine(self, client: TestClient) -> None:
        resp = client.get(
            "/api/runs/nonexistent:default/logs/issue-1",
            params={"session_id": "sess-abc", "tail": "50"},
        )
        assert resp.status_code == 200
        assert resp.text == ""

    def test_empty_session_id_falls_back_to_issue_lookup(self, client: TestClient) -> None:
        # ?session_id= (empty string) is treated as "not provided" so issue-level
        # lookup still happens. Locks the manager's truthy check, not just `is not None`.
        resp = client.get(
            "/api/runs/nonexistent:default/logs/issue-1",
            params={"session_id": "", "tail": "100"},
        )
        assert resp.status_code == 200
        assert resp.text == ""


class TestSessionPrompt:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default/sessions/sess-abc/prompt")
        assert resp.status_code == 404
        assert "prompt" in resp.json()["error"]


class TestRetryIssue:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/runs/nonexistent:default/retry/abc")
        assert resp.status_code == 404


class TestUnblockWorker:
    def test_run_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/api/runs/nonexistent:default/unblock/issue-1",
            json={"message": "hello"},
        )
        assert resp.status_code == 404

    def test_missing_message(self, client: TestClient) -> None:
        resp = client.post(
            "/api/runs/nonexistent:default/unblock/issue-1",
            json={},
        )
        assert resp.status_code == 400
        assert "message" in resp.json()["error"]
