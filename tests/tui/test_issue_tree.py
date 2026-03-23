from __future__ import annotations

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
            tree.update_state(state)
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
            tree.update_state(state)
            await pilot.pause()
            label_text = str(tree.root.children[0].label)
            assert "work" in label_text

    @pytest.mark.asyncio
    async def test_label_shows_worker_spinner(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={"id-1": _make_issue("Active Task", "work", worker_active=True)},
                worker_queues={},
            )
            tree.update_state(state)
            await pilot.pause()
            label_text = str(tree.root.children[0].label)
            assert "⟳" in label_text

    @pytest.mark.asyncio
    async def test_no_spinner_when_worker_inactive(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={"id-1": _make_issue("Idle Task", "work", worker_active=False)},
                worker_queues={},
            )
            tree.update_state(state)
            await pilot.pause()
            label_text = str(tree.root.children[0].label)
            assert "⟳" not in label_text
