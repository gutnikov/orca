from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult

from orca.tui.widgets.phases_panel import PhasesPanel


def _make_session(
    session_id: str,
    issue_id: str = "issue-1",
    state: str = "planning",
    started_at: str = "2026-01-01T00:00:00+00:00",
    completed_at: str | None = "2026-01-01T00:01:00+00:00",
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "session_id": session_id,
        "issue_id": issue_id,
        "state": state,
        "started_at": started_at,
    }
    if completed_at is not None:
        d["completed_at"] = completed_at
    return d


def _get_static_text(panel: PhasesPanel) -> str:
    """Extract the plain text content from the panel's static widget."""
    content = panel._static._Static__content  # type: ignore[attr-defined]
    return str(content)


class PhasesPanelApp(App[None]):
    def compose(self) -> ComposeResult:
        yield PhasesPanel()


class TestPhasesPanel:
    @pytest.mark.asyncio
    async def test_empty_state(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            assert panel is not None
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_show_phases_renders_sessions(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                _make_session("s1", state="planning", completed_at="2026-01-01T00:01:00+00:00"),
                _make_session("s2", state="implementing", completed_at="2026-01-01T00:05:00+00:00"),
                _make_session("s3", state="reviewing", completed_at=None),
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = _get_static_text(panel)
            assert "reviewing" in text
            assert "implementing" in text
            assert "planning" in text

    @pytest.mark.asyncio
    async def test_show_phases_reversed_order(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                _make_session("s1", state="planning", completed_at="2026-01-01T00:01:00+00:00"),
                _make_session("s2", state="implementing", completed_at="2026-01-01T00:05:00+00:00"),
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = _get_static_text(panel)
            assert text.index("implementing") < text.index("planning")

    @pytest.mark.asyncio
    async def test_no_pending_phases_shown(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                _make_session("s1", state="planning", completed_at="2026-01-01T00:01:00+00:00"),
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = _get_static_text(panel)
            assert "planning" in text
            assert "○" not in text

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            panel.show_phases("issue-1", [_make_session("s1", state="planning")])
            await pilot.pause()
            panel.clear()
            await pilot.pause()
            text = _get_static_text(panel)
            assert "planning" not in text
