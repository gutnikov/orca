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
