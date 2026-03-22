"""Serialization round-trip scenario tests simulating system restarts."""

from __future__ import annotations

import json
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    State,
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

CAPPED_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
initial: work
states:
  work:
    max_workers: 1
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

DECOMPOSE_CONFIG_YAML = """\
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
          values: [done, decompose]
          description: "Result"
          values_description:
            done: "Complete"
            decompose: "Split"
        sub_issues:
          type: list
          required_when:
            - decompose
          items: "$issue"
          description: "Sub-issues"
    on:
      done: done
      decompose:
        action: decompose
  done:
    terminal: true
"""


def _counter(start: int = 0) -> Callable[[], str]:
    n = start

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def _empty_state() -> State:
    return State(issues={}, worker_queues={})


def _roundtrip(state: State) -> State:
    return State.from_dict(json.loads(json.dumps(state.to_dict())))


class TestEmptyStateRoundtrip:
    """Empty state serializes and deserializes correctly."""

    def test_empty_state_roundtrip(self) -> None:
        state = _empty_state()
        restored = _roundtrip(state)
        assert restored.issues == {}
        assert restored.worker_queues == {}


class TestMidWorkflowRoundtrip:
    """Create issue, advance to active. Serialize, restore. Continue to completion."""

    def test_mid_workflow_roundtrip(self) -> None:
        config = parse_config(MINIMAL_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create issue — dispatched immediately (active initial state)
        state, effects = reduce(config, state, CreateEvent(issue_id="S-1", fields={"title": "Serialize"}), gen)
        assert state.issues["S-1"].worker_active is True

        # Serialize and restore (simulating restart)
        state = _roundtrip(state)

        # Verify state survived
        assert state.issues["S-1"].state == "work"
        assert state.issues["S-1"].worker_active is True
        assert state.issues["S-1"].fields == {"title": "Serialize"}

        # Continue processing on restored state — complete the issue
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="S-1", result={"outcome": "done"}),
            gen,
        )
        assert state.issues["S-1"].state == "done"
        assert state.issues["S-1"].worker_active is False
        assert len(state.issues["S-1"].result_history) == 1


class TestBlockedStateRoundtrip:
    """Decompose parent with children. Serialize. Verify relationships survive."""

    def test_blocked_state_roundtrip(self) -> None:
        config = parse_config(DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create root
        state, _effects = reduce(config, state, CreateEvent(issue_id="ROOT-1", fields={"title": "Root"}), gen)

        # Decompose into 2 children
        state, _effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="ROOT-1",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "c1", "fields": {"title": "Child 1"}},
                        {"key": "c2", "fields": {"title": "Child 2"}},
                    ],
                },
            ),
            gen,
        )

        # Identify child IDs
        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "ROOT-1"]
        assert len(child_ids) == 2

        # Serialize and restore
        state = _roundtrip(state)

        # Verify parent's decomposition relationships survive
        for child_id in child_ids:
            assert state.issues[child_id].decomposed_from == "ROOT-1"

        # Root should not be active (blocked by children)
        assert state.issues["ROOT-1"].worker_active is False

        # Complete children and verify root unblocks
        for child_id in child_ids:
            state, _effects = reduce(
                config,
                state,
                WorkerResultEvent(issue_id=child_id, result={"outcome": "done"}),
                gen,
            )

        # Root should now be dispatched (unblocked)
        assert state.issues["ROOT-1"].worker_active is True


class TestQueueOrderSurvivesRoundtrip:
    """Create 5 issues in max_workers:1. Serialize, restore. Complete first, verify next activates."""

    def test_queue_order_survives_roundtrip(self) -> None:
        config = parse_config(CAPPED_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        all_ids = [f"Q-{i}" for i in range(1, 6)]
        for iid in all_ids:
            state, _effects = reduce(config, state, CreateEvent(issue_id=iid, fields={"title": f"Issue {iid}"}), gen)

        # Only Q-1 active, rest queued
        assert state.issues["Q-1"].worker_active is True
        for iid in all_ids[1:]:
            assert state.issues[iid].worker_active is False

        # Serialize and restore
        state = _roundtrip(state)

        # Verify queue survived
        assert state.worker_queues.get("work") == ["Q-2", "Q-3", "Q-4", "Q-5"]

        # Complete Q-1 on restored state
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="Q-1", result={"outcome": "done"}),
            gen,
        )
        assert state.issues["Q-1"].state == "done"

        # Q-2 should have been activated (next in queue)
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1
        assert dispatch_effects[0].issue_id == "Q-2"
        assert state.issues["Q-2"].worker_active is True


class TestDeepResultHistoryRoundtrip:
    """Issue loops 10 times. Serialize. Verify 10 history entries survive. Continue to completion."""

    def test_deep_result_history_roundtrip(self) -> None:
        config = parse_config(SELF_LOOP_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create — refine is active
        state, _effects = reduce(config, state, CreateEvent(issue_id="H-1", fields={"title": "History"}), gen)

        # Loop 10 times
        for _ in range(10):
            state, _effects = reduce(
                config,
                state,
                WorkerResultEvent(issue_id="H-1", result={"outcome": "again"}),
                gen,
            )

        assert len(state.issues["H-1"].result_history) == 10

        # Serialize and restore
        state = _roundtrip(state)

        # Verify all 10 entries survive
        assert len(state.issues["H-1"].result_history) == 10
        assert all(e.state == "refine" for e in state.issues["H-1"].result_history)
        assert all(e.result["outcome"] == "again" for e in state.issues["H-1"].result_history)

        # Continue to completion after roundtrip
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="H-1", result={"outcome": "done"}),
            gen,
        )
        assert state.issues["H-1"].state == "done"
        assert len(state.issues["H-1"].result_history) == 11
        assert state.issues["H-1"].result_history[-1].result["outcome"] == "done"
