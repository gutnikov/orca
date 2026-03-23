from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from orca.engine.types import Issue, State
from orca.tui.widgets.issue_detail import IssueDetail


def _make_issue(title: str = "Test", description: str = "Some description") -> Issue:
    return Issue(
        fields={"title": title, "description": description},
        state="triage",
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
    )


class IssueDetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield IssueDetail()


class TestIssueDetail:
    @pytest.mark.asyncio
    async def test_shows_placeholder_when_no_issue_selected(self) -> None:
        app = IssueDetailApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            await pilot.pause()
            assert detail._current_issue_id is None

    @pytest.mark.asyncio
    async def test_shows_issue_content(self) -> None:
        app = IssueDetailApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            state = State(
                issues={"id-1": _make_issue("My Title", "My **bold** text")},
                worker_queues={},
            )
            detail.show_issue("id-1", state)
            await pilot.pause()
            assert detail._current_issue_id == "id-1"

    @pytest.mark.asyncio
    async def test_clears_when_issue_not_in_state(self) -> None:
        app = IssueDetailApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            state = State(issues={}, worker_queues={})
            detail.show_issue("nonexistent", state)
            await pilot.pause()
            assert detail._current_issue_id is None
