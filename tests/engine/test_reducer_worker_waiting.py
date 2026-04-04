from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    ErrorEffect,
    State,
    WorkerResumedEvent,
    WorkerWaitingEvent,
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


class TestWorkerWaiting:
    """WorkerWaitingEvent appends event_log entry, no effects."""

    def test_happy_path(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        assert state.issues["A"].worker_active is True

        state, effects = reduce(
            config,
            state,
            WorkerWaitingEvent(issue_id="A", reason="waiting for deploy", timestamp="t1"),
            gen,
            _clock(),
        )

        assert effects == []
        assert state.issues["A"].worker_active is True
        log_types = [e.type for e in state.issues["A"].event_log]
        assert "worker_waiting" in log_types

    def test_nonexistent_issue(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, effects = reduce(
            config,
            state,
            WorkerWaitingEvent(issue_id="NOPE", reason="", timestamp="t0"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "NOPE" in effects[0].message

    def test_worker_not_active(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        state.issues["A"].worker_active = False

        state, effects = reduce(
            config,
            state,
            WorkerWaitingEvent(issue_id="A", reason="waiting for deploy", timestamp="t1"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)

    def test_terminal_state(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        state.issues["A"].state = "done"
        state.issues["A"].worker_active = True

        state, effects = reduce(
            config,
            state,
            WorkerWaitingEvent(issue_id="A", reason="waiting for deploy", timestamp="t1"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)


class TestWorkerResumed:
    """WorkerResumedEvent appends event_log entry with message, no effects."""

    def test_happy_path(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        assert state.issues["A"].worker_active is True

        state, effects = reduce(
            config,
            state,
            WorkerResumedEvent(issue_id="A", message="PR merged", timestamp="t1"),
            gen,
            _clock(),
        )

        assert effects == []
        assert state.issues["A"].worker_active is True
        resumed_entries = [e for e in state.issues["A"].event_log if e.type == "worker_resumed"]
        assert len(resumed_entries) == 1
        assert resumed_entries[0].data == {"message": "PR merged"}

    def test_nonexistent_issue(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, effects = reduce(
            config,
            state,
            WorkerResumedEvent(issue_id="NOPE", message="hi", timestamp="t0"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)

    def test_worker_not_active(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        state.issues["A"].worker_active = False

        state, effects = reduce(
            config,
            state,
            WorkerResumedEvent(issue_id="A", message="hi", timestamp="t1"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)

    def test_terminal_state(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        state.issues["A"].state = "done"
        state.issues["A"].worker_active = True

        state, effects = reduce(
            config,
            state,
            WorkerResumedEvent(issue_id="A", message="hi", timestamp="t1"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
