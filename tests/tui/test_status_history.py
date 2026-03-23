from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from orca.engine.types import EventLogEntry, Issue
from orca.tui.widgets.status_history import StatusHistory, build_timeline


def _make_issue_with_log(entries: list[EventLogEntry], current_state: str = "review") -> Issue:
    return Issue(
        fields={"title": "Test", "description": "desc"},
        state=current_state,
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=entries,
    )


class TestBuildTimeline:
    def test_empty_event_log(self) -> None:
        issue = _make_issue_with_log([], current_state="triage")
        result = build_timeline(issue)
        assert "triage" in result

    def test_shows_state_transitions_in_order(self) -> None:
        entries = [
            EventLogEntry(timestamp="2026-01-01T00:00:00+00:00", type="created", data={"state": "triage"}),
            EventLogEntry(
                timestamp="2026-01-01T00:01:00+00:00",
                type="state_changed",
                data={"from": "triage", "to": "work", "outcome": "ready"},
            ),
            EventLogEntry(
                timestamp="2026-01-01T00:02:00+00:00",
                type="state_changed",
                data={"from": "work", "to": "review", "outcome": "completed"},
            ),
        ]
        issue = _make_issue_with_log(entries, current_state="review")
        result = build_timeline(issue)
        assert "triage" in result
        assert "work" in result
        assert "review" in result
        assert "ready" in result
        assert "completed" in result

    def test_current_state_uses_filled_marker(self) -> None:
        entries = [
            EventLogEntry(timestamp="2026-01-01T00:00:00+00:00", type="created", data={"state": "triage"}),
        ]
        issue = _make_issue_with_log(entries, current_state="triage")
        result = build_timeline(issue)
        assert "◉" in result

    def test_past_states_use_open_marker(self) -> None:
        entries = [
            EventLogEntry(timestamp="2026-01-01T00:00:00+00:00", type="created", data={"state": "triage"}),
            EventLogEntry(
                timestamp="2026-01-01T00:01:00+00:00",
                type="state_changed",
                data={"from": "triage", "to": "work", "outcome": "ready"},
            ),
        ]
        issue = _make_issue_with_log(entries, current_state="work")
        result = build_timeline(issue)
        assert "●" in result
        assert "◉" in result


class StatusHistoryApp(App[None]):
    def compose(self) -> ComposeResult:
        yield StatusHistory()


class TestStatusHistoryWidget:
    @pytest.mark.asyncio
    async def test_shows_placeholder_when_no_issue(self) -> None:
        app = StatusHistoryApp()
        async with app.run_test() as pilot:
            widget = app.query_one(StatusHistory)
            await pilot.pause()
            assert widget._current_issue_id is None
