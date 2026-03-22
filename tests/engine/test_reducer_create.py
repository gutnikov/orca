from __future__ import annotations

from collections.abc import Callable

from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    EnumFieldDef,
    ErrorEffect,
    FieldDef,
    State,
    StateDef,
    StateMachineConfig,
    WorkerDef,
)


def _counter() -> Callable[[], str]:
    n = 0

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"id-{n}"

    return next_id


def _passive_initial_config() -> StateMachineConfig:
    """Config where initial state 'backlog' is passive (no worker)."""
    return StateMachineConfig(
        issue_fields={"title": FieldDef(type="string", description="Title")},
        initial="backlog",
        states={
            "backlog": StateDef(),
            "todo": StateDef(
                worker=WorkerDef(
                    result_format={
                        "outcome": EnumFieldDef(values=["start"], description="Decision"),
                    }
                ),
                on={},
            ),
            "done": StateDef(terminal=True),
        },
    )


def _active_initial_config() -> StateMachineConfig:
    """Config where initial state 'todo' is active (has worker)."""
    return StateMachineConfig(
        issue_fields={"title": FieldDef(type="string", description="Title")},
        initial="todo",
        states={
            "todo": StateDef(
                worker=WorkerDef(
                    result_format={
                        "outcome": EnumFieldDef(values=["start"], description="Decision"),
                    }
                ),
                on={},
            ),
            "done": StateDef(terminal=True),
        },
    )


class TestCreatePassiveInitial:
    def test_creates_issue_with_correct_fields(self) -> None:
        config = _passive_initial_config()
        state = State(issues={}, worker_queues={})
        event = CreateEvent(issue_id="A", fields={"title": "My Issue"})

        new_state, effects = reduce(config, state, event, _counter())

        assert "A" in new_state.issues
        issue = new_state.issues["A"]
        assert issue.fields == {"title": "My Issue"}
        assert issue.state == "backlog"
        assert issue.worker_active is False
        assert issue.decomposed_from is None
        assert issue.depends_on == []
        assert issue.result_history == []

    def test_no_effects_for_passive_initial(self) -> None:
        config = _passive_initial_config()
        state = State(issues={}, worker_queues={})
        event = CreateEvent(issue_id="A", fields={"title": "My Issue"})

        _new_state, effects = reduce(config, state, event, _counter())

        assert effects == []


class TestCreateActiveInitial:
    def test_dispatch_effect_emitted(self) -> None:
        config = _active_initial_config()
        state = State(issues={}, worker_queues={})
        event = CreateEvent(issue_id="A", fields={"title": "My Issue"})

        new_state, effects = reduce(config, state, event, _counter())

        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "A"
        assert effects[0].state == "todo"
        assert new_state.issues["A"].worker_active is True


class TestCreateDuplicate:
    def test_error_on_duplicate_id(self) -> None:
        config = _passive_initial_config()
        state = State(issues={}, worker_queues={})
        event = CreateEvent(issue_id="A", fields={"title": "First"})
        state, _effects = reduce(config, state, event, _counter())

        # Try creating again with the same ID
        event2 = CreateEvent(issue_id="A", fields={"title": "Second"})
        new_state, effects = reduce(config, state, event2, _counter())

        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert effects[0].issue_id == "A"
        # Original issue unchanged
        assert new_state.issues["A"].fields == {"title": "First"}
