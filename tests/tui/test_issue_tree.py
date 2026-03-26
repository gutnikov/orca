from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult

from orca.engine.types import EventLogEntry, Issue, State, StateDef, StateMachineConfig
from orca.tui.widgets.issue_tree import (
    IssueTree,
    _compute_failed_states,
    _extract_failure_errors,
    _extract_result_outcomes,
    _pending_steps,
    _progress_bar_text,
)


def _make_issue(
    title: str = "Test",
    state: str = "triage",
    worker_active: bool = False,
    decomposed_from: str | None = None,
    depends_on: list[str] | None = None,
    visit_counts: dict[str, int] | None = None,
    failure_count: int = 0,
    event_log: list[EventLogEntry] | None = None,
) -> Issue:
    return Issue(
        fields={"title": title, "description": "desc"},
        state=state,
        worker_active=worker_active,
        decomposed_from=decomposed_from,
        depends_on=depends_on or [],
        event_log=event_log or [EventLogEntry(timestamp="2026-01-01T00:00:00+00:00", type="created", data={})],
        visit_counts=visit_counts or {},
        failure_count=failure_count,
    )


def _make_config(
    states: dict[str, StateDef] | None = None,
    initial: str = "a",
) -> StateMachineConfig:
    if states is None:
        states = {
            "a": StateDef(),
            "b": StateDef(),
            "c": StateDef(),
            "done": StateDef(terminal=True),
        }
    return StateMachineConfig(
        issue_fields={},
        initial=initial,
        states=states,
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
            # At least 2 session nodes (may also have progress bar etc without config)
            session_nodes = [c for c in issue_node.children if c.data and c.data.startswith("session:")]
            assert len(session_nodes) == 2
            # Active run should have a spinner character
            active_label = str(session_nodes[1].label)
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
            session_nodes = [c for c in issue_node.children if c.data and c.data.startswith("session:")]
            assert session_nodes[0].data == "session:s1"


class TestProgressBar:
    def test_progress_bar_text(self) -> None:
        """3 non-terminal states: a visited+done, b active, c pending."""
        config = _make_config()
        visit_counts = {"a": 1}
        bar = _progress_bar_text(config, visit_counts, current_state="b", failed_states=set())
        assert bar is not None
        text = str(bar)
        # 3 non-terminal states = 3 block chars
        assert text == "███"

    def test_progress_bar_with_failure(self) -> None:
        """State b failed."""
        config = _make_config()
        visit_counts = {"a": 1, "b": 1}
        bar = _progress_bar_text(config, visit_counts, current_state="b", failed_states={"b"})
        assert bar is not None
        text = str(bar)
        assert text == "███"

    def test_progress_bar_no_non_terminal(self) -> None:
        """All states terminal -> None."""
        config = _make_config(states={"done": StateDef(terminal=True)})
        result = _progress_bar_text(config, {}, current_state="done", failed_states=set())
        assert result is None


class TestPendingSteps:
    def test_pending_steps(self) -> None:
        """Only a visited, b and c should be pending."""
        config = _make_config()
        visit_counts = {"a": 1}
        pending = _pending_steps(config, visit_counts)
        assert pending == ["b", "c"]

    def test_pending_steps_all_visited(self) -> None:
        config = _make_config()
        visit_counts = {"a": 1, "b": 1, "c": 1}
        pending = _pending_steps(config, visit_counts)
        assert pending == []


class TestExtractResultOutcomes:
    def test_extract_result_outcomes(self) -> None:
        event_log = [
            EventLogEntry(
                timestamp="2026-01-01T00:00:00+00:00",
                type="worker_result",
                data={"state": "planning", "outcome": "ready"},
            ),
            EventLogEntry(
                timestamp="2026-01-01T00:01:00+00:00",
                type="worker_result",
                data={"state": "scoping", "outcome": "decompose"},
            ),
        ]
        outcomes = _extract_result_outcomes(event_log)
        assert outcomes == {"planning": "ready", "scoping": "decompose"}

    def test_extract_result_outcomes_last_wins(self) -> None:
        event_log = [
            EventLogEntry(
                timestamp="2026-01-01T00:00:00+00:00",
                type="worker_result",
                data={"state": "planning", "outcome": "review"},
            ),
            EventLogEntry(
                timestamp="2026-01-01T00:01:00+00:00",
                type="worker_result",
                data={"state": "planning", "outcome": "ready"},
            ),
        ]
        outcomes = _extract_result_outcomes(event_log)
        assert outcomes == {"planning": "ready"}


class TestExtractFailureErrors:
    def test_extract_failure_errors(self) -> None:
        event_log = [
            EventLogEntry(
                timestamp="2026-01-01T00:00:00+00:00",
                type="worker_failed",
                data={"state": "planning", "error": "exit code 1"},
            ),
        ]
        errors = _extract_failure_errors(event_log)
        assert errors == {"planning": "exit code 1"}

    def test_extract_failure_errors_last_wins(self) -> None:
        event_log = [
            EventLogEntry(
                timestamp="2026-01-01T00:00:00+00:00",
                type="worker_failed",
                data={"state": "planning", "error": "timeout"},
            ),
            EventLogEntry(
                timestamp="2026-01-01T00:01:00+00:00",
                type="worker_failed",
                data={"state": "planning", "error": "exit code 1"},
            ),
        ]
        errors = _extract_failure_errors(event_log)
        assert errors == {"planning": "exit code 1"}


class TestComputeFailedStates:
    def test_compute_failed_states(self) -> None:
        issue = _make_issue(
            event_log=[
                EventLogEntry(
                    timestamp="2026-01-01T00:00:00+00:00",
                    type="worker_result",
                    data={"state": "a"},
                ),
                EventLogEntry(
                    timestamp="2026-01-01T00:01:00+00:00",
                    type="worker_failed",
                    data={"state": "b"},
                ),
            ]
        )
        failed = _compute_failed_states(issue)
        assert failed == {"b"}

    def test_compute_failed_states_recovered(self) -> None:
        """If a state failed then succeeded, it's not failed."""
        issue = _make_issue(
            event_log=[
                EventLogEntry(
                    timestamp="2026-01-01T00:00:00+00:00",
                    type="worker_failed",
                    data={"state": "a"},
                ),
                EventLogEntry(
                    timestamp="2026-01-01T00:01:00+00:00",
                    type="worker_result",
                    data={"state": "a"},
                ),
            ]
        )
        failed = _compute_failed_states(issue)
        assert failed == set()
