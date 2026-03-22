from __future__ import annotations

from orca.engine.formatting import format_issues
from orca.engine.types import (
    EventLogEntry,
    FieldDef,
    Issue,
    State,
    StateDef,
    StateMachineConfig,
)


def _make_config(
    states: dict[str, StateDef] | None = None,
) -> StateMachineConfig:
    return StateMachineConfig(
        issue_fields={"title": FieldDef(type="string", description="t")},
        initial="todo",
        states=states
        or {
            "todo": StateDef(),
            "work": StateDef(),
            "done": StateDef(terminal=True),
        },
    )


def _make_issue(
    state: str = "todo",
    created_ts: str | None = "2026-01-01T00:00:00Z",
    decomposed_from: str | None = None,
    depends_on: list[str] | None = None,
) -> Issue:
    event_log: list[EventLogEntry] = []
    if created_ts is not None:
        event_log.append(EventLogEntry(timestamp=created_ts, type="created", data={}))
    return Issue(
        fields={"title": "Test"},
        state=state,
        worker_active=False,
        decomposed_from=decomposed_from,
        depends_on=depends_on or [],
        event_log=event_log,
        visit_counts={state: 1},
        hop_count=0,
    )


class TestFormatIssues:
    def test_empty_state(self) -> None:
        state = State(issues={}, worker_queues={})
        result = format_issues(state, _make_config(), now="2026-01-01T00:00:00Z")
        assert result == ""

    def test_single_root_issue(self) -> None:
        state = State(
            issues={"ISSUE-1": _make_issue(state="todo")},
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T00:00:00Z")
        assert "ISSUE-1 [todo] ... 0m" in result

    def test_terminal_issue_no_marker(self) -> None:
        state = State(
            issues={"ISSUE-1": _make_issue(state="done")},
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T00:30:00Z")
        assert "ISSUE-1 [done] 30m" in result
        assert "..." not in result

    def test_parent_with_children(self) -> None:
        state = State(
            issues={
                "ISSUE-1": _make_issue(state="work"),
                "ISSUE-3": _make_issue(state="todo", decomposed_from="ISSUE-1"),
                "ISSUE-2": _make_issue(state="done", decomposed_from="ISSUE-1"),
            },
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T01:00:00Z")
        lines = result.split("\n")
        # Root first
        assert "ISSUE-1 [work] ... 1h" in lines[0]
        # Children sorted: ISSUE-2 before ISSUE-3
        assert "\u251c\u2500\u2500 ISSUE-2 [done] 1h" in lines[1]
        assert "\u2514\u2500\u2500 ISSUE-3 [todo] ... 1h" in lines[2]

    def test_depends_on_annotation(self) -> None:
        state = State(
            issues={
                "ISSUE-1": _make_issue(state="work", depends_on=["ISSUE-2"]),
                "ISSUE-2": _make_issue(state="done"),
            },
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T00:00:00Z")
        assert "depends on: ISSUE-2" in result

    def test_elapsed_time_minutes(self) -> None:
        state = State(
            issues={"I-1": _make_issue(state="todo")},
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T00:30:00Z")
        assert "30m" in result

    def test_elapsed_time_hours(self) -> None:
        state = State(
            issues={"I-1": _make_issue(state="todo")},
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T02:15:00Z")
        assert "2h 15m" in result

    def test_elapsed_time_days(self) -> None:
        state = State(
            issues={"I-1": _make_issue(state="todo")},
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-02T03:00:00Z")
        assert "1d 3h" in result

    def test_worker_queues_shown(self) -> None:
        state = State(
            issues={
                "I-1": _make_issue(state="work"),
                "I-2": _make_issue(state="work"),
            },
            worker_queues={"work": ["I-3", "I-4"]},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T00:00:00Z")
        assert "Queued in 'work': I-3, I-4" in result

    def test_no_created_event_shows_question_mark(self) -> None:
        state = State(
            issues={"I-1": _make_issue(state="todo", created_ts=None)},
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T00:00:00Z")
        assert "I-1 [todo] ... ?" in result

    def test_sort_order_by_id(self) -> None:
        state = State(
            issues={
                "C-1": _make_issue(state="todo"),
                "A-1": _make_issue(state="todo"),
                "B-1": _make_issue(state="todo"),
            },
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T00:00:00Z")
        lines = [line for line in result.split("\n") if line.strip()]
        assert lines[0].startswith("A-1")
        assert lines[1].startswith("B-1")
        assert lines[2].startswith("C-1")

    def test_deep_nesting(self) -> None:
        state = State(
            issues={
                "I-1": _make_issue(state="work"),
                "I-2": _make_issue(state="work", decomposed_from="I-1"),
                "I-3": _make_issue(state="done", decomposed_from="I-2"),
            },
            worker_queues={},
        )
        result = format_issues(state, _make_config(), now="2026-01-01T01:00:00Z")
        lines = result.split("\n")
        assert "I-1 [work] ... 1h" in lines[0]
        assert "\u2514\u2500\u2500 I-2 [work] ... 1h" in lines[1]
        assert "    \u2514\u2500\u2500 I-3 [done] 1h" in lines[2]
