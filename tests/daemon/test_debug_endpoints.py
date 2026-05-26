from pathlib import Path

import pytest
from starlette.testclient import TestClient

from orca.daemon.http_api import create_app
from orca.daemon.manager import RunManager


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    manager = RunManager(tmp_path)
    app = create_app(manager)
    return TestClient(app)


def test_get_debug_review_returns_404_when_no_run(client: TestClient) -> None:
    r = client.get("/api/runs/none:none/issues/x/debug")
    assert r.status_code == 404


def test_post_debug_decide_400_or_404_when_no_pause(client: TestClient) -> None:
    r = client.post(
        "/api/runs/none:none/issues/x/debug/decide",
        json={"action": "accept", "comments": []},
    )
    assert r.status_code in (400, 404)


def test_post_debug_decide_400_on_invalid_action(client: TestClient) -> None:
    r = client.post(
        "/api/runs/none:none/issues/x/debug/decide",
        json={"action": "weird", "comments": []},
    )
    assert r.status_code == 400
    assert "invalid action" in r.json().get("error", "").lower()


def test_get_debug_review_with_attempt_param_404_when_no_run(client: TestClient) -> None:
    r = client.get("/api/runs/none:none/issues/x/debug?attempt=0")
    assert r.status_code == 404


def test_get_debug_attempts_returns_empty_list_for_unknown_run(client: TestClient) -> None:
    r = client.get("/api/runs/none:none/issues/x/debug/attempts")
    assert r.status_code == 200
    assert r.json() == []


def test_get_debug_review_400_on_non_integer_attempt(client: TestClient) -> None:
    r = client.get("/api/runs/none:none/issues/x/debug?attempt=abc")
    assert r.status_code == 400
    assert "invalid attempt" in r.json().get("error", "").lower()


def test_get_debug_review_returns_not_pending_for_live_mode_miss(client: TestClient) -> None:
    """Live-mode 404 must return "not_pending" — the orca-prompt-config-rewrite
    playbook branches on this exact string."""
    r = client.get("/api/runs/none:none/issues/x/debug")
    assert r.status_code == 404
    assert r.json() == {"error": "not_pending"}


def test_get_debug_review_returns_not_found_for_past_mode_miss(client: TestClient) -> None:
    """Past-mode 404 (attempt= supplied but out of range / unknown run) returns
    a distinct "not_found" so consumers can tell the two failure modes apart."""
    r = client.get("/api/runs/none:none/issues/x/debug?attempt=0")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}
