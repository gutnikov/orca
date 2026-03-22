"""Edge case and boundary condition scenario tests."""

from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
    WorkerFailedEvent,
    WorkerResultEvent,
)

MINIMAL_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
initial: work
states:
  work:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Result"
          values_description:
            done: "Complete"
    on:
      done: done
  done:
    terminal: true
"""

PASSIVE_CHAIN_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
initial: triage
states:
  triage:
    worker:
      result_format:
        outcome:
          type: enum
          values: [ready, done]
          description: "Result"
          values_description:
            ready: "Needs review"
            done: "Complete"
    on:
      ready: review
      done: done
  review: {}
  approved: {}
  done:
    terminal: true
"""

SELF_LOOP_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
initial: refine
states:
  refine:
    worker:
      result_format:
        outcome:
          type: enum
          values: [again, done]
          description: "Result"
          values_description:
            again: "Refine more"
            done: "Complete"
    on:
      again: refine
      done: done
  done:
    terminal: true
"""

TS = "2026-01-01T00:00:00Z"


def _clock(value: str = TS) -> Callable[[], str]:
    return lambda: value


def _counter(start: int = 0) -> Callable[[], str]:
    n = start

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def _empty_state() -> State:
    return State(issues={}, worker_queues={})


class TestMinimalSingleStateMachine:
    """Simplest possible: create issue, complete, done."""

    def test_minimal_single_state_machine(self) -> None:
        config = parse_config(MINIMAL_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create — initial state is active, so dispatch happens
        state, effects = reduce(
            config, state, CreateEvent(issue_id="M-1", fields={"title": "Minimal"}, timestamp=TS), gen, _clock()
        )
        assert state.issues["M-1"].state == "work"
        assert state.issues["M-1"].worker_active is True
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)

        # Complete
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="M-1", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["M-1"].state == "done"
        assert state.issues["M-1"].worker_active is False
        assert effects == []
        worker_results = [e for e in state.issues["M-1"].event_log if e.type == "worker_result"]
        assert len(worker_results) == 1


class TestPassiveToPassiveAdvance:
    """Advance between passive states: review → approved."""

    def test_passive_to_passive_advance(self) -> None:
        config = parse_config(PASSIVE_CHAIN_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create issue (triage is active, dispatched immediately)
        state, effects = reduce(
            config, state, CreateEvent(issue_id="P-1", fields={"title": "Passive"}, timestamp=TS), gen, _clock()
        )
        assert state.issues["P-1"].state == "triage"
        assert state.issues["P-1"].worker_active is True

        # Complete triage with "ready" outcome → transitions to review (passive)
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P-1", result={"outcome": "ready"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["P-1"].state == "review"
        assert state.issues["P-1"].worker_active is False
        assert effects == []

        # Advance review → approved (both passive)
        state, effects = reduce(
            config, state, AdvanceEvent(issue_id="P-1", target_state="approved", timestamp=TS), gen, _clock()
        )
        assert state.issues["P-1"].state == "approved"
        assert state.issues["P-1"].worker_active is False
        assert effects == []


class TestAdvanceToTerminal:
    """Advance from passive directly to terminal."""

    def test_advance_to_terminal(self) -> None:
        config = parse_config(PASSIVE_CHAIN_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create issue (triage is active)
        state, _effects = reduce(
            config, state, CreateEvent(issue_id="P-1", fields={"title": "Skip"}, timestamp=TS), gen, _clock()
        )

        # Complete triage → review (passive)
        state, _effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P-1", result={"outcome": "ready"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["P-1"].state == "review"

        # Advance review → done (passive to terminal)
        state, effects = reduce(
            config, state, AdvanceEvent(issue_id="P-1", target_state="done", timestamp=TS), gen, _clock()
        )
        assert state.issues["P-1"].state == "done"
        assert effects == []


class TestSelfLoopState:
    """Loop 3 times in refine, then done. Verify 4 event_log worker_result entries."""

    def test_self_loop_state(self) -> None:
        config = parse_config(SELF_LOOP_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create — refine is active, dispatched immediately
        state, effects = reduce(
            config, state, CreateEvent(issue_id="L-1", fields={"title": "Loop"}, timestamp=TS), gen, _clock()
        )
        assert state.issues["L-1"].state == "refine"
        assert state.issues["L-1"].worker_active is True

        # Loop 3 times
        for _i in range(3):
            state, effects = reduce(
                config,
                state,
                WorkerResultEvent(issue_id="L-1", result={"outcome": "again"}, timestamp=TS),
                gen,
                _clock(),
            )
            assert state.issues["L-1"].state == "refine"
            assert state.issues["L-1"].worker_active is True
            assert len(effects) == 1
            assert isinstance(effects[0], DispatchWorkerEffect)

        # Final: done
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="L-1", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["L-1"].state == "done"
        assert state.issues["L-1"].worker_active is False

        # 3 "again" + 1 "done" = 4 entries
        worker_results = [e for e in state.issues["L-1"].event_log if e.type == "worker_result"]
        assert len(worker_results) == 4
        outcomes = [e.data["outcome"] for e in worker_results]
        assert outcomes == ["again", "again", "again", "done"]


class TestDuplicateCreateErrors:
    """Create same ID twice. ErrorEffect, original unchanged."""

    def test_duplicate_create_errors(self) -> None:
        config = parse_config(MINIMAL_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        state, _effects = reduce(
            config, state, CreateEvent(issue_id="D-1", fields={"title": "First"}, timestamp=TS), gen, _clock()
        )
        original_fields = state.issues["D-1"].fields.copy()

        state, effects = reduce(
            config, state, CreateEvent(issue_id="D-1", fields={"title": "Duplicate"}, timestamp=TS), gen, _clock()
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "already exists" in effects[0].message

        # Original unchanged
        assert state.issues["D-1"].fields == original_fields


class TestWorkerResultOnTerminalErrors:
    """Send WorkerResult to done issue. ErrorEffect."""

    def test_worker_result_on_terminal_errors(self) -> None:
        config = parse_config(MINIMAL_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create and complete
        state, _effects = reduce(
            config, state, CreateEvent(issue_id="T-1", fields={"title": "Terminal"}, timestamp=TS), gen, _clock()
        )
        state, _effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="T-1", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["T-1"].state == "done"

        # Try to send result to terminal issue
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="T-1", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "terminal" in effects[0].message


class TestWorkerResultUnknownOutcomeErrors:
    """Send result with invalid outcome. ErrorEffect, state unchanged."""

    def test_worker_result_unknown_outcome_errors(self) -> None:
        config = parse_config(MINIMAL_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        state, _effects = reduce(
            config, state, CreateEvent(issue_id="U-1", fields={"title": "Unknown"}, timestamp=TS), gen, _clock()
        )
        assert state.issues["U-1"].worker_active is True

        # Send invalid outcome
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="U-1", result={"outcome": "invalid_value"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)

        # worker_active stays True (validation is before mutation)
        assert state.issues["U-1"].worker_active is True
        assert state.issues["U-1"].state == "work"


class TestDoubleWorkerResultRaceCondition:
    """Two WorkerResults for same issue. Second errors because worker_active is False."""

    def test_double_worker_result_race_condition(self) -> None:
        config = parse_config(MINIMAL_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        state, _effects = reduce(
            config, state, CreateEvent(issue_id="R-1", fields={"title": "Race"}, timestamp=TS), gen, _clock()
        )
        assert state.issues["R-1"].worker_active is True

        # First result succeeds
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="R-1", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["R-1"].state == "done"
        assert not any(isinstance(e, ErrorEffect) for e in effects)

        # Second result errors (terminal state)
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="R-1", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)


class TestEventsOnNonexistentIssue:
    """Advance, WorkerResult, WorkerFailed on nonexistent ID. All produce ErrorEffect."""

    def test_events_on_nonexistent_issue(self) -> None:
        config = parse_config(MINIMAL_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # AdvanceEvent on nonexistent
        state, effects = reduce(
            config, state, AdvanceEvent(issue_id="NOPE-1", target_state="done", timestamp=TS), gen, _clock()
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "does not exist" in effects[0].message

        # WorkerResultEvent on nonexistent
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="NOPE-2", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "does not exist" in effects[0].message

        # WorkerFailedEvent on nonexistent
        state, effects = reduce(
            config,
            state,
            WorkerFailedEvent(issue_id="NOPE-3", error="boom", timestamp=TS),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "does not exist" in effects[0].message


class TestWorkerFailedWhenNotActiveErrors:
    """WorkerFailed when worker_active=False. ErrorEffect."""

    def test_worker_failed_when_not_active_errors(self) -> None:
        config = parse_config(MINIMAL_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create issue — active initial state, so dispatched
        state, _effects = reduce(
            config, state, CreateEvent(issue_id="F-1", fields={"title": "Fail"}, timestamp=TS), gen, _clock()
        )
        assert state.issues["F-1"].worker_active is True

        # Complete the worker so worker_active becomes False
        state, _effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="F-1", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["F-1"].worker_active is False

        # WorkerFailed on issue with worker_active=False (terminal state, but checked first)
        state, effects = reduce(
            config,
            state,
            WorkerFailedEvent(issue_id="F-1", error="boom", timestamp=TS),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
