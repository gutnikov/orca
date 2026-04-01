from __future__ import annotations

from collections.abc import Callable

from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    DispatchWorkerEffect,
    EnumFieldDef,
    ErrorEffect,
    FieldDef,
    Issue,
    State,
    StateDef,
    StateMachineConfig,
    TypeDef,
    WorkerDef,
)


def _counter() -> Callable[[], str]:
    n = 0

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"id-{n}"

    return next_id


def _clock(value: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: value


def _make_issue(
    state: str = "backlog",
    worker_active: bool = False,
    decomposed_from: str | None = None,
    depends_on: list[str] | None = None,
) -> Issue:
    return Issue(
        type="default",
        fields={"title": "Test"},
        state=state,
        worker_active=worker_active,
        decomposed_from=decomposed_from,
        depends_on=depends_on or [],
        event_log=[],
        visit_counts={},
        hop_count=0,
    )


def _config() -> StateMachineConfig:
    """Config with passive 'backlog', active 'todo' and 'implementing', terminal 'done'."""
    return StateMachineConfig(
        root_type="default",
        types={
            "default": TypeDef(
                fields={"title": FieldDef(type="string", description="Title")},
                initial="backlog",
                states={
                    "backlog": StateDef(),
                    "review": StateDef(),
                    "todo": StateDef(
                        worker=WorkerDef(
                            kind="claude-code",
                            prompt="prompts/default.md",
                            result_format={
                                "outcome": EnumFieldDef(values=["start"], description="Decision"),
                            },
                        ),
                        on={},
                    ),
                    "implementing": StateDef(
                        worker=WorkerDef(
                            kind="claude-code",
                            prompt="prompts/default.md",
                            result_format={
                                "outcome": EnumFieldDef(values=["complete"], description="Outcome"),
                            },
                        ),
                        on={},
                    ),
                },
            )
        },
    )


class TestAdvancePassiveToActive:
    def test_state_changes_and_dispatch(self) -> None:
        config = _config()
        state = State(
            issues={"A": _make_issue(state="backlog")},
            worker_queues={},
        )
        event = AdvanceEvent(issue_id="A", target_state="todo", timestamp="2026-01-01T00:00:00Z")

        new_state, effects = reduce(config, state, event, _counter(), _clock())

        assert new_state.issues["A"].state == "todo"
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "A"
        assert effects[0].state == "todo"


class TestAdvanceFromActive:
    def test_error_when_in_active_state(self) -> None:
        config = _config()
        state = State(
            issues={"A": _make_issue(state="todo")},
            worker_queues={},
        )
        event = AdvanceEvent(issue_id="A", target_state="implementing", timestamp="2026-01-01T00:00:00Z")

        _new_state, effects = reduce(config, state, event, _counter(), _clock())

        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert effects[0].issue_id == "A"


class TestAdvanceBlocked:
    def test_error_when_blocked(self) -> None:
        config = _config()
        state = State(
            issues={
                "A": _make_issue(state="backlog"),
                "B": _make_issue(state="implementing", decomposed_from="A"),
            },
            worker_queues={},
        )
        event = AdvanceEvent(issue_id="A", target_state="todo", timestamp="2026-01-01T00:00:00Z")

        _new_state, effects = reduce(config, state, event, _counter(), _clock())

        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert effects[0].issue_id == "A"


class TestAdvanceNonexistent:
    def test_error_for_missing_issue(self) -> None:
        config = _config()
        state = State(issues={}, worker_queues={})
        event = AdvanceEvent(issue_id="Z", target_state="todo", timestamp="2026-01-01T00:00:00Z")

        _new_state, effects = reduce(config, state, event, _counter(), _clock())

        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert effects[0].issue_id == "Z"


class TestAdvanceToNonexistentState:
    def test_error_for_unknown_target(self) -> None:
        config = _config()
        state = State(
            issues={"A": _make_issue(state="backlog")},
            worker_queues={},
        )
        event = AdvanceEvent(issue_id="A", target_state="nonexistent", timestamp="2026-01-01T00:00:00Z")

        _new_state, effects = reduce(config, state, event, _counter(), _clock())

        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert effects[0].issue_id == "A"


class TestAdvancePassiveToPassive:
    def test_state_changes_no_dispatch(self) -> None:
        config = _config()
        state = State(
            issues={"A": _make_issue(state="backlog")},
            worker_queues={},
        )
        event = AdvanceEvent(issue_id="A", target_state="review", timestamp="2026-01-01T00:00:00Z")

        new_state, effects = reduce(config, state, event, _counter(), _clock())

        assert new_state.issues["A"].state == "review"
        assert effects == []


class TestAdvanceToTerminal:
    def test_state_changes_to_terminal(self) -> None:
        config = _config()
        state = State(
            issues={"A": _make_issue(state="backlog")},
            worker_queues={},
        )
        event = AdvanceEvent(issue_id="A", target_state="done", timestamp="2026-01-01T00:00:00Z")

        new_state, effects = reduce(config, state, event, _counter(), _clock())

        assert new_state.issues["A"].state == "done"
        # Terminal states have no worker, so no dispatch
        assert effects == []
