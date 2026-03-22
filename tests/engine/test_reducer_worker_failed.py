from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
    WorkerFailedEvent,
    WorkerResultEvent,
)


def _counter() -> Callable[[], str]:
    n = 0

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"id-{n}"

    return next_id


class TestWorkerFailedRetries:
    """Test 1: Worker failed retries — worker_active stays True, DispatchWorkerEffect emitted."""

    def test_retry_on_failure(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create issue -> lands in todo (active), worker dispatched
        state, _ = reduce(config, state, CreateEvent(issue_id="A", fields={"title": "T"}), gen)
        assert state.issues["A"].worker_active is True
        assert state.issues["A"].state == "todo"

        # Worker fails
        state, effects = reduce(config, state, WorkerFailedEvent(issue_id="A", error="timeout"), gen)

        # worker_active stays True (slot retained)
        assert state.issues["A"].worker_active is True
        # DispatchWorkerEffect emitted for retry
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1
        assert dispatch_effects[0].issue_id == "A"
        assert dispatch_effects[0].state == "todo"
        # No error effects
        assert not any(isinstance(e, ErrorEffect) for e in effects)


class TestWorkerFailedRetainsSlot:
    """Test 2: In max_workers capped state, queued issue stays queued after failure."""

    def test_queued_issue_stays_queued(self, max_workers_config_yaml: str) -> None:
        config = parse_config(max_workers_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create A, advance to apply state (max_workers=1)
        state, _ = reduce(config, state, CreateEvent(issue_id="A", fields={"title": "A"}), gen)
        state, _ = reduce(config, state, WorkerResultEvent(issue_id="A", result={"outcome": "start"}), gen)
        state, _ = reduce(config, state, WorkerResultEvent(issue_id="A", result={"outcome": "ready"}), gen)
        assert state.issues["A"].state == "apply"
        assert state.issues["A"].worker_active is True

        # Create B, advance to apply state — should be queued
        state, _ = reduce(config, state, CreateEvent(issue_id="B", fields={"title": "B"}), gen)
        state, _ = reduce(config, state, WorkerResultEvent(issue_id="B", result={"outcome": "start"}), gen)
        state, _ = reduce(config, state, WorkerResultEvent(issue_id="B", result={"outcome": "ready"}), gen)
        assert state.issues["B"].state == "apply"
        assert state.issues["B"].worker_active is False
        assert "B" in state.worker_queues.get("apply", [])

        # A's worker fails — slot is retained, B stays queued
        state, effects = reduce(config, state, WorkerFailedEvent(issue_id="A", error="crash"), gen)

        # A still holds slot
        assert state.issues["A"].worker_active is True
        # B still queued, not dispatched
        assert state.issues["B"].worker_active is False
        assert "B" in state.worker_queues.get("apply", [])

        # Only A gets a retry dispatch, not B
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1
        assert dispatch_effects[0].issue_id == "A"


class TestWorkerFailedNonexistentIssue:
    """Test 3: Worker failed on nonexistent issue -> ErrorEffect."""

    def test_nonexistent_issue_error(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, effects = reduce(config, state, WorkerFailedEvent(issue_id="NOPE", error="timeout"), gen)
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "NOPE" in effects[0].message


class TestWorkerFailedNotActive:
    """Test 4: Worker failed when worker_active is False -> ErrorEffect."""

    def test_inactive_worker_error(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(config, state, CreateEvent(issue_id="A", fields={"title": "T"}), gen)
        # Manually deactivate worker
        state.issues["A"].worker_active = False

        state, effects = reduce(config, state, WorkerFailedEvent(issue_id="A", error="timeout"), gen)
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)


class TestWorkerFailedRepeated:
    """Test 5: Worker failed 3 times in a row — slot retained each time, retry each time."""

    def test_three_consecutive_failures(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(config, state, CreateEvent(issue_id="A", fields={"title": "T"}), gen)
        assert state.issues["A"].worker_active is True

        for i in range(3):
            state, effects = reduce(config, state, WorkerFailedEvent(issue_id="A", error=f"failure-{i}"), gen)
            # Slot retained every time
            assert state.issues["A"].worker_active is True
            # Retry dispatched every time
            dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
            assert len(dispatch_effects) == 1
            assert dispatch_effects[0].issue_id == "A"
            assert dispatch_effects[0].state == "todo"
            # No errors
            assert not any(isinstance(e, ErrorEffect) for e in effects)
