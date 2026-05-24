"""Tests for the auto-open-review-URL behavior on debug pause."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from orca.orchestrator.orchestrator import Orchestrator


def _make_orchestrator(tmp_path: Path) -> Orchestrator:
    """Build a bare-minimum Orchestrator instance for testing _auto_open_review_url.

    We don't drive the run loop here — only need the instance method available.
    """
    repo_root = tmp_path
    persistence = MagicMock()
    # state.json under <repo>/.orca-state/runs/<branch>/<workflow>/state.json
    run_dir = repo_root / ".orca-state" / "runs" / "main" / "default"
    run_dir.mkdir(parents=True)
    persistence.state_path = run_dir / "state.json"

    orch = Orchestrator(
        config=MagicMock(),
        state=MagicMock(),
        root_branch="main",
        persistence=persistence,
        branches=MagicMock(),
        workers={},
        generate_id=lambda: "id",
        now=lambda: "now",
        worktree_mgr=MagicMock(),
        repo_root=repo_root,
    )
    return orch


def test_opt_out_via_env_var(tmp_path: Path) -> None:
    """ORCA_NO_AUTO_OPEN=1 short-circuits the helper before any browser call."""
    orch = _make_orchestrator(tmp_path)
    with (
        patch.dict(os.environ, {"ORCA_NO_AUTO_OPEN": "1"}),
        patch("webbrowser.open") as wb_open,
    ):
        orch._auto_open_review_url("issue-1")
        # Give the (would-be) thread a beat — should never run
        import time

        time.sleep(0.05)
        wb_open.assert_not_called()


def test_no_browser_port_no_open(tmp_path: Path) -> None:
    """If the daemon hasn't bound a browser port, the helper bails silently."""
    orch = _make_orchestrator(tmp_path)
    os.environ.pop("ORCA_NO_AUTO_OPEN", None)
    with (
        patch("orca.daemon.lifecycle.read_browser_port", return_value=None),
        patch("webbrowser.open") as wb_open,
    ):
        orch._auto_open_review_url("issue-1")
        import time

        time.sleep(0.05)
        wb_open.assert_not_called()


def test_opens_url_with_correct_components(tmp_path: Path) -> None:
    """When a port is available, the helper opens the well-formed URL."""
    orch = _make_orchestrator(tmp_path)
    os.environ.pop("ORCA_NO_AUTO_OPEN", None)

    opened_urls: list[str] = []

    def fake_open(url: str, new: int = 0) -> bool:
        opened_urls.append(url)
        return True

    with (
        patch("orca.daemon.lifecycle.read_browser_port", return_value=7891),
        patch("webbrowser.open", side_effect=fake_open),
    ):
        orch._auto_open_review_url("a51c63f2-6d4c")
        # Let the detached thread run
        import time

        time.sleep(0.2)

    assert len(opened_urls) == 1, f"expected one open call, got {opened_urls!r}"
    url = opened_urls[0]
    # URL built from run layout: <branch>:<workflow> + /<issue_id>
    assert url == "http://localhost:7891/debug/main:default/a51c63f2-6d4c"


def test_does_not_block(tmp_path: Path) -> None:
    """The helper returns immediately even if webbrowser.open is slow."""
    orch = _make_orchestrator(tmp_path)
    os.environ.pop("ORCA_NO_AUTO_OPEN", None)

    def slow_open(url: str, new: int = 0) -> bool:
        import time

        time.sleep(2.0)
        return True

    with (
        patch("orca.daemon.lifecycle.read_browser_port", return_value=7891),
        patch("webbrowser.open", side_effect=slow_open),
    ):
        import time

        t0 = time.time()
        orch._auto_open_review_url("issue-1")
        elapsed = time.time() - t0
    assert elapsed < 0.5, f"helper blocked for {elapsed:.2f}s — should run in a daemon thread"
