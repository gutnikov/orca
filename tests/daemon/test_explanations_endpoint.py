"""Tests for /api/explanations/{flow} — browser-facing read-only endpoint."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from orca.daemon.http_api import create_browser_app
from orca.daemon.manager import RunManager


@pytest.fixture()
def manager(tmp_path: Path) -> RunManager:
    return RunManager(tmp_path)


@pytest.fixture()
def client(manager: RunManager) -> TestClient:
    return TestClient(create_browser_app(manager))


def _write_explanation(root: Path, flow: str, lang: str, payload: Mapping[str, Any]) -> Path:
    dir_ = root / ".orca-state" / "explanations"
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{flow}.{lang}.json"
    path.write_text(json.dumps(payload))
    return path


def test_get_explanation_returns_200_when_file_exists(manager: RunManager, client: TestClient) -> None:
    payload = {
        "flow": "run-evals",
        "language": "en",
        "title": "Run the eval workflow",
        "summary": "Picks an eval and runs it.",
        "diagram_mermaid": "stateDiagram-v2\n[*] --> select_eval\nselect_eval --> [*] : done",
        "states": [],
        "generated_at": "2026-05-21T10:00:00Z",
    }
    _write_explanation(manager.repo_root, "run-evals", "en", payload)

    resp = client.get("/api/explanations/run-evals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["flow"] == "run-evals"
    assert body["language"] == "en"
    assert body["title"] == "Run the eval workflow"


def test_get_explanation_honours_lang_query_param(manager: RunManager, client: TestClient) -> None:
    payload_en = {
        "flow": "run-evals",
        "language": "en",
        "title": "Run the eval workflow",
        "summary": "EN",
        "diagram_mermaid": "x",
        "states": [],
        "generated_at": "t",
    }
    payload_ru = {
        "flow": "run-evals",
        "language": "ru",
        "title": "Поток запуска",
        "summary": "RU",
        "diagram_mermaid": "x",
        "states": [],
        "generated_at": "t",
    }
    _write_explanation(manager.repo_root, "run-evals", "en", payload_en)
    _write_explanation(manager.repo_root, "run-evals", "ru", payload_ru)

    en = client.get("/api/explanations/run-evals?lang=en").json()
    ru = client.get("/api/explanations/run-evals?lang=ru").json()
    assert en["title"] == "Run the eval workflow"
    assert ru["title"] == "Поток запуска"


def test_get_explanation_returns_404_when_missing(client: TestClient) -> None:
    resp = client.get("/api/explanations/no-such-flow")
    assert resp.status_code == 404
    assert "not_found" in resp.json().get("error", "")


def test_get_explanation_returns_500_when_corrupted(manager: RunManager, client: TestClient) -> None:
    dir_ = manager.repo_root / ".orca-state" / "explanations"
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "bad.en.json").write_text("{not valid json")

    resp = client.get("/api/explanations/bad")
    assert resp.status_code == 500
    assert "corrupted" in resp.json().get("error", "")
