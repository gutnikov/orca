from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.widgets.issue_tree import IssueTree


def _make_issue(
    title: str = "Test",
    state: str = "triage",
    worker_active: bool = False,
    decomposed_from: str | None = None,
    depends_on: list[str] | None = None,
) -> Issue:
    return Issue(
        fields={"title": title, "description": "desc"},
        state=state,
        worker_active=worker_active,
        decomposed_from=decomposed_from,
        depends_on=depends_on or [],
        event_log=[EventLogEntry(timestamp="2026-01-01T00:00:00+00:00", type="created", data={})],
    )


class IssueTreeApp(App[None]):
    def compose(self) -> ComposeResult:
        yield IssueTree()


class TestIssueTree:
    @pytest.mark.asyncio
    async def test_builds_tree_from_state(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={
                    "root": _make_issue("Root Task", "work"),
                    "child-1": _make_issue("Child One", "triage", decomposed_from="root"),
                },
                worker_queues={},
            )
            tree.update_state(state, [])
            await pilot.pause()
            root_node = tree.root
            assert len(root_node.children) == 1
            top_node = root_node.children[0]
            assert "Root Task" in str(top_node.label)
            assert len(top_node.children) == 1
            assert "Child One" in str(top_node.children[0].label)

    @pytest.mark.asyncio
    async def test_label_shows_state_badge(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={"id-1": _make_issue("My Task", "work")},
                worker_queues={},
            )
            tree.update_state(state, [])
            await pilot.pause()
            label_text = str(tree.root.children[0].label)
            assert "work" in label_text

    @pytest.mark.asyncio
    async def test_worker_runs_shown_as_children(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={"id-1": _make_issue("My Task", "planning", worker_active=True)},
                worker_queues={},
            )
            sessions: list[dict[str, Any]] = [
                {
                    "issue_id": "id-1",
                    "state": "scoping",
                    "session_id": "s1",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "completed_at": "2026-01-01T00:01:00+00:00",
                },
                {
                    "issue_id": "id-1",
                    "state": "planning",
                    "session_id": "s2",
                    "started_at": "2026-01-01T00:01:00+00:00",
                    "completed_at": None,
                },
            ]
            tree.update_state(state, sessions)
            await pilot.pause()
            issue_node = tree.root.children[0]
            assert len(issue_node.children) == 2
            # Active run should have a spinner character
            active_label = str(issue_node.children[1].label)
            assert "planning" in active_label

    @pytest.mark.asyncio
    async def test_node_data_prefixed(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={"id-1": _make_issue("My Task", "work")},
                worker_queues={},
            )
            sessions = [
                {
                    "issue_id": "id-1",
                    "state": "scoping",
                    "session_id": "s1",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "completed_at": "2026-01-01T00:01:00+00:00",
                },
            ]
            tree.update_state(state, sessions)
            await pilot.pause()
            issue_node = tree.root.children[0]
            assert issue_node.data == "issue:id-1"
            assert issue_node.children[0].data == "session:s1"
