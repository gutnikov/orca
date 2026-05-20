"""Tests for the browser-facing form endpoints (full app + browser-only app)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from orca.daemon.http_api import create_app, create_browser_app
from orca.daemon.manager import RunManager


@pytest.fixture()
def manager(tmp_path: Path) -> RunManager:
    return RunManager(tmp_path)


@pytest.fixture()
def client(manager: RunManager) -> TestClient:
    return TestClient(create_app(manager))


@pytest.fixture()
def browser_client(manager: RunManager) -> TestClient:
    return TestClient(create_browser_app(manager))


SCHEMA: dict[str, Any] = {
    "title": "Sign in",
    "steps": [
        {
            "blocks": [
                {"kind": "field", "name": "email", "type": "email", "label": "Email", "required": True},
                {"kind": "field", "name": "remember", "type": "checkbox", "label": "Remember me"},
            ]
        }
    ],
}


def _pending_info() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "submitted_at": None,
        "state": "implementing",
        "reason": "need auth",
        "started_waiting_at": "2026-05-20T14:18:02Z",
    }


class TestGetForm:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/runs/missing/forms/issue-1")
        assert resp.status_code == 404

    def test_ok(self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(manager, "get_pending_form", lambda r, i: _pending_info())
        resp = client.get("/api/runs/r1/forms/issue-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == "r1"
        assert body["issue_id"] == "issue-1"
        assert body["schema"] == SCHEMA
        assert body["context"] == {
            "state": "implementing",
            "reason": "need auth",
            "started_waiting_at": "2026-05-20T14:18:02Z",
        }

    def test_already_submitted(self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch) -> None:
        info = {**_pending_info(), "submitted_at": "2026-05-20T14:30:00Z"}
        monkeypatch.setattr(manager, "get_pending_form", lambda r, i: info)
        resp = client.get("/api/runs/r1/forms/issue-1")
        assert resp.status_code == 410


class TestSubmitForm:
    def test_invalid_json_body(self, client: TestClient) -> None:
        resp = client.post(
            "/api/runs/r1/forms/issue-1/submit",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/runs/missing/forms/issue-1/submit", json={"values": {}})
        assert resp.status_code == 404

    def test_already_submitted(self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch) -> None:
        info = {**_pending_info(), "submitted_at": "2026-05-20T14:30:00Z"}
        monkeypatch.setattr(manager, "get_pending_form", lambda r, i: info)
        resp = client.post("/api/runs/r1/forms/issue-1/submit", json={"values": {"email": "a@b.c"}})
        assert resp.status_code == 410

    def test_validation_failure_required(
        self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(manager, "get_pending_form", lambda r, i: _pending_info())
        resp = client.post("/api/runs/r1/forms/issue-1/submit", json={"values": {}})
        assert resp.status_code == 422
        body = resp.json()
        assert body["field_errors"] == {"email": "required"}

    def test_validation_failure_unknown(
        self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(manager, "get_pending_form", lambda r, i: _pending_info())
        resp = client.post(
            "/api/runs/r1/forms/issue-1/submit",
            json={"values": {"email": "a@b.c", "junk": 1}},
        )
        assert resp.status_code == 422
        assert resp.json()["field_errors"] == {"junk": "unknown_field"}

    def test_ok(self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _submit(run_id: str, issue_id: str, envelope: dict[str, Any]) -> str:
            captured["run_id"] = run_id
            captured["issue_id"] = issue_id
            captured["envelope"] = envelope
            return "ok"

        monkeypatch.setattr(manager, "get_pending_form", lambda r, i: _pending_info())
        monkeypatch.setattr(manager, "submit_form", _submit)
        resp = client.post(
            "/api/runs/r1/forms/issue-1/submit",
            json={"values": {"email": "a@b.c", "remember": True}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert captured["envelope"] == {"submitted": True, "values": {"email": "a@b.c", "remember": True}}

    def test_cancel(self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _submit(run_id: str, issue_id: str, envelope: dict[str, Any]) -> str:
            captured["envelope"] = envelope
            return "ok"

        monkeypatch.setattr(manager, "get_pending_form", lambda r, i: _pending_info())
        monkeypatch.setattr(manager, "submit_form", _submit)
        resp = client.post("/api/runs/r1/forms/issue-1/submit", json={"cancelled": True})
        assert resp.status_code == 200
        assert captured["envelope"] == {"submitted": False, "cancelled": True}

    def test_worker_not_waiting(self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(manager, "get_pending_form", lambda r, i: _pending_info())
        monkeypatch.setattr(manager, "submit_form", lambda r, i, e: "not_waiting")
        resp = client.post(
            "/api/runs/r1/forms/issue-1/submit",
            json={"values": {"email": "a@b.c"}},
        )
        assert resp.status_code == 409


class TestListPending:
    def test_empty(self, client: TestClient) -> None:
        resp = client.get("/api/forms/pending")
        assert resp.status_code == 200
        assert resp.json() == {"pending": []}

    def test_populated(self, client: TestClient, manager: RunManager, monkeypatch: pytest.MonkeyPatch) -> None:
        entries = [
            {
                "run_id": "r1",
                "issue_id": "issue-1",
                "state": "implementing",
                "title": "Sign in",
                "started_waiting_at": "2026-05-20T14:18:02Z",
                "url": "/forms/r1/issue-1",
            }
        ]
        monkeypatch.setattr(manager, "list_pending_forms", lambda: entries)
        resp = client.get("/api/forms/pending")
        assert resp.status_code == 200
        assert resp.json() == {"pending": entries}


class TestBrowserApp:
    """The browser-only sub-app exposes form endpoints and the SPA mount,
    and intentionally returns 404 for the privileged routes."""

    def test_exposes_form_routes(self, browser_client: TestClient) -> None:
        # 404 (no run), not 404 (route missing) — i.e. the route is registered.
        resp = browser_client.get("/api/runs/missing/forms/issue-1")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not_found"}

    def test_pending_list_works(self, browser_client: TestClient) -> None:
        resp = browser_client.get("/api/forms/pending")
        assert resp.status_code == 200

    def test_does_not_expose_start(self, browser_client: TestClient) -> None:
        # /api/runs/start is privileged — not present on the browser app.
        resp = browser_client.post("/api/runs/start", json={})
        # Returns 404 because the static-files mount catches unknown /api/ paths.
        # The important thing: it does NOT actually start a run.
        assert resp.status_code in (404, 405)

    def test_does_not_expose_unblock(self, browser_client: TestClient) -> None:
        resp = browser_client.post("/api/runs/r1/unblock/issue-1", json={"message": "x"})
        assert resp.status_code in (404, 405)

    def test_serves_index_for_unknown_path(self, browser_client: TestClient) -> None:
        """StaticFiles(html=True) serves index.html for SPA-style client routes."""
        resp = browser_client.get("/forms/r1/issue-1")
        assert resp.status_code == 200
        assert "<!doctype html>" in resp.text.lower() or "<html" in resp.text.lower()
