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


class TestRetryIssue:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/runs/nonexistent:default/retry/abc")
        assert resp.status_code == 404
