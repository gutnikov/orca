from __future__ import annotations

from orca.engine.dispatch import (
    backfill_queue,
    build_issue_context,
    build_result_format,
    get_children,
    is_blocked,
    remove_from_queue,
    try_dispatch,
)
from orca.engine.types import (
    DispatchWorkerEffect,
    Effect,
    EnumFieldDef,
    EventLogEntry,
    FieldDef,
    Issue,
    ListFieldDef,
    State,
    StateDef,
    StateMachineConfig,
    StringFieldDef,
    WorkerDef,
)


def _make_config(
    states: dict[str, StateDef] | None = None,
    initial: str = "todo",
) -> StateMachineConfig:
    if states is None:
        states = {
            "todo": StateDef(
                worker=WorkerDef(
                    result_format={
                        "outcome": EnumFieldDef(values=["start"], description="Decision"),
                    }
                ),
                on={},
            ),
            "implementing": StateDef(
                worker=WorkerDef(
                    result_format={
                        "outcome": EnumFieldDef(values=["complete"], description="Outcome"),
                    }
                ),
                on={},
            ),
            "apply": StateDef(
                worker=WorkerDef(
                    result_format={
                        "outcome": EnumFieldDef(values=["applied"], description="Apply result"),
                    }
                ),
                on={},
                max_workers=1,
            ),
            "done": StateDef(terminal=True),
        }
    return StateMachineConfig(
        issue_fields={"title": FieldDef(type="string", description="Title")},
        initial=initial,
        states=states,
    )


def _make_issue(
    state: str = "todo",
    worker_active: bool = False,
    decomposed_from: str | None = None,
    depends_on: list[str] | None = None,
    fields: dict[str, object] | None = None,
    event_log: list[EventLogEntry] | None = None,
    visit_counts: dict[str, int] | None = None,
    hop_count: int = 0,
) -> Issue:
    return Issue(
        fields=fields or {"title": "Test"},
        state=state,
        worker_active=worker_active,
        decomposed_from=decomposed_from,
        depends_on=depends_on or [],
        event_log=event_log or [],
        visit_counts=visit_counts or {},
        hop_count=hop_count,
    )


class TestIsBlocked:
    def test_not_blocked_no_children_no_deps(self) -> None:
        config = _make_config()
        state = State(issues={"A": _make_issue()}, worker_queues={})
        assert is_blocked(state, config, "A") is False

    def test_blocked_non_terminal_children(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo"),
                "B": _make_issue(state="implementing", decomposed_from="A"),
            },
            worker_queues={},
        )
        assert is_blocked(state, config, "A") is True

    def test_not_blocked_all_children_terminal(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo"),
                "B": _make_issue(state="done", decomposed_from="A"),
            },
            worker_queues={},
        )
        assert is_blocked(state, config, "A") is False

    def test_blocked_non_terminal_depends_on(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo", depends_on=["B"]),
                "B": _make_issue(state="implementing"),
            },
            worker_queues={},
        )
        assert is_blocked(state, config, "A") is True

    def test_not_blocked_all_deps_terminal(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo", depends_on=["B"]),
                "B": _make_issue(state="done"),
            },
            worker_queues={},
        )
        assert is_blocked(state, config, "A") is False


class TestGetChildren:
    def test_returns_children(self) -> None:
        state = State(
            issues={
                "A": _make_issue(),
                "B": _make_issue(decomposed_from="A"),
                "C": _make_issue(decomposed_from="A"),
                "D": _make_issue(decomposed_from="B"),
            },
            worker_queues={},
        )
        children = get_children(state, "A")
        assert sorted(children) == ["B", "C"]

    def test_no_children(self) -> None:
        state = State(issues={"A": _make_issue()}, worker_queues={})
        assert get_children(state, "A") == []


class TestBuildIssueContext:
    def test_includes_resolved_children(self) -> None:
        state = State(
            issues={
                "A": _make_issue(state="todo", fields={"title": "Parent"}),
                "B": _make_issue(
                    state="done",
                    decomposed_from="A",
                    fields={"title": "Child1"},
                    event_log=[
                        EventLogEntry(
                            timestamp="2026-03-22T10:00:00Z",
                            type="worker_result",
                            data={"outcome": "complete"},
                        )
                    ],
                ),
            },
            worker_queues={},
        )
        ctx = build_issue_context(state, "A")
        assert ctx["fields"] == {"title": "Parent"}
        assert ctx["event_log"] == []
        assert ctx["decomposed_from"] is None
        assert ctx["depends_on"] == []
        assert len(ctx["children"]) == 1
        child = ctx["children"][0]
        assert child["issue_id"] == "B"
        assert child["fields"] == {"title": "Child1"}
        assert child["state"] == "done"
        assert child["event_log"] == [
            {"timestamp": "2026-03-22T10:00:00Z", "type": "worker_result", "data": {"outcome": "complete"}}
        ]


class TestBuildResultFormat:
    def test_enum_field(self) -> None:
        config = _make_config()
        result = build_result_format(config, "todo")
        assert result["outcome"] == {
            "type": "enum",
            "values": ["start"],
            "description": "Decision",
            "values_description": {},
        }

    def test_string_field(self) -> None:
        states = {
            "review": StateDef(
                worker=WorkerDef(
                    result_format={
                        "outcome": EnumFieldDef(values=["approve"], description="Decision"),
                        "reason": StringFieldDef(description="Explanation", required_when=["reject"]),
                    }
                ),
                on={},
            ),
            "done": StateDef(terminal=True),
        }
        config = _make_config(states=states, initial="review")
        result = build_result_format(config, "review")
        assert result["reason"] == {
            "type": "string",
            "description": "Explanation",
            "required_when": ["reject"],
        }

    def test_list_field(self) -> None:
        states = {
            "scoping": StateDef(
                worker=WorkerDef(
                    result_format={
                        "outcome": EnumFieldDef(values=["decompose"], description="Decision"),
                        "sub_issues": ListFieldDef(
                            description="Sub-issues", items="$issue", required_when=["decompose"]
                        ),
                    }
                ),
                on={},
            ),
            "done": StateDef(terminal=True),
        }
        config = _make_config(states=states, initial="scoping")
        result = build_result_format(config, "scoping")
        assert result["sub_issues"] == {
            "type": "list",
            "description": "Sub-issues",
            "items": "$issue",
            "required_when": ["decompose"],
        }


class TestTryDispatch:
    def test_dispatch_no_limit(self) -> None:
        config = _make_config()
        state = State(issues={"A": _make_issue(state="todo")}, worker_queues={})
        effects: list[Effect] = []
        try_dispatch(config, state, "A", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "A"
        assert effects[0].state == "todo"
        assert state.issues["A"].worker_active is True

    def test_dispatch_under_limit(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply"),
            },
            worker_queues={},
        )
        effects: list[Effect] = []
        try_dispatch(config, state, "A", effects)
        assert len(effects) == 1
        assert state.issues["A"].worker_active is True

    def test_dispatch_at_limit_queues(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply", worker_active=True),
                "B": _make_issue(state="apply"),
            },
            worker_queues={},
        )
        effects: list[Effect] = []
        try_dispatch(config, state, "B", effects)
        assert len(effects) == 0
        assert state.issues["B"].worker_active is False
        assert state.worker_queues["apply"] == ["B"]

    def test_blocked_issue_not_dispatched(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo"),
                "B": _make_issue(state="implementing", decomposed_from="A"),
            },
            worker_queues={},
        )
        effects: list[Effect] = []
        try_dispatch(config, state, "A", effects)
        assert len(effects) == 0
        assert state.issues["A"].worker_active is False

    def test_no_worker_not_dispatched(self) -> None:
        config = _make_config()
        state = State(issues={"A": _make_issue(state="done")}, worker_queues={})
        effects: list[Effect] = []
        try_dispatch(config, state, "A", effects)
        assert len(effects) == 0


class TestBackfillQueue:
    def test_backfill_pops_next(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply"),
                "B": _make_issue(state="apply"),
            },
            worker_queues={"apply": ["A", "B"]},
        )
        effects: list[Effect] = []
        backfill_queue(config, state, "apply", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "A"
        assert state.issues["A"].worker_active is True
        assert state.worker_queues["apply"] == ["B"]

    def test_backfill_skips_blocked_decomposition(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply"),
                "B": _make_issue(state="apply"),
                "C": _make_issue(state="implementing", decomposed_from="A"),
            },
            worker_queues={"apply": ["A", "B"]},
        )
        effects: list[Effect] = []
        backfill_queue(config, state, "apply", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "B"
        assert state.worker_queues["apply"] == ["A"]

    def test_backfill_skips_blocked_dependency(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply", depends_on=["C"]),
                "B": _make_issue(state="apply"),
                "C": _make_issue(state="implementing"),
            },
            worker_queues={"apply": ["A", "B"]},
        )
        effects: list[Effect] = []
        backfill_queue(config, state, "apply", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "B"
        assert state.worker_queues["apply"] == ["A"]


class TestRemoveFromQueue:
    def test_remove_existing(self) -> None:
        state = State(issues={}, worker_queues={"apply": ["A", "B", "C"]})
        remove_from_queue(state, "apply", "B")
        assert state.worker_queues["apply"] == ["A", "C"]

    def test_remove_nonexistent_no_error(self) -> None:
        state = State(issues={}, worker_queues={"apply": ["A"]})
        remove_from_queue(state, "apply", "Z")
        assert state.worker_queues["apply"] == ["A"]

    def test_remove_from_missing_queue_no_error(self) -> None:
        state = State(issues={}, worker_queues={})
        remove_from_queue(state, "apply", "A")  # should not raise
