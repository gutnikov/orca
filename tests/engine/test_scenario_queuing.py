"""Queuing stress and max_workers capacity scenario tests."""

from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    State,
    WorkerFailedEvent,
    WorkerResultEvent,
)

CAPPED_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
initial: work
states:
  work:
    max_workers: 3
    worker:
      kind: claude-code
      prompt: prompts/default.md
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

CAPPED_DECOMPOSE_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
initial: work
states:
  work:
    max_workers: 2
    worker:
      kind: claude-code
      prompt: prompts/default.md
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


class TestMaxWorkersRespected:
    """Create 10 issues. First 3 active, 7 queued. Complete one, verify new one activates."""

    def test_max_workers_respected(self) -> None:
        config = parse_config(CAPPED_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create 10 issues
        all_ids = [f"Q-{i}" for i in range(1, 11)]
        for iid in all_ids:
            state, _effects = reduce(
                config, state, CreateEvent(issue_id=iid, fields={"title": f"Issue {iid}"}, timestamp=TS), gen, _clock()
            )

        # First 3 should be active, remaining 7 queued
        active = [iid for iid in all_ids if state.issues[iid].worker_active]
        queued = [iid for iid in all_ids if not state.issues[iid].worker_active]
        assert len(active) == 3
        assert len(queued) == 7
        assert active == ["Q-1", "Q-2", "Q-3"]

        # Complete Q-1 -> a queued issue should activate
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="Q-1", result={"outcome": "done"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["Q-1"].state == "done"

        # Should have dispatched one new worker
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1

        # Still 3 active workers total
        active_after = [iid for iid in all_ids if state.issues[iid].worker_active and state.issues[iid].state == "work"]
        assert len(active_after) == 3


class TestWorkerFailureRetainsSlotInCappedState:
    """5 issues, 3 active. Fail first active 3 times. Slot retained each time."""

    def test_worker_failure_retains_slot_in_capped_state(self) -> None:
        config = parse_config(CAPPED_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        all_ids = [f"Q-{i}" for i in range(1, 6)]
        for iid in all_ids:
            state, _effects = reduce(
                config, state, CreateEvent(issue_id=iid, fields={"title": f"Issue {iid}"}, timestamp=TS), gen, _clock()
            )

        # 3 active, 2 queued
        active = [iid for iid in all_ids if state.issues[iid].worker_active]
        assert len(active) == 3

        # Fail Q-1 three times
        for _ in range(3):
            state, effects = reduce(
                config,
                state,
                WorkerFailedEvent(issue_id="Q-1", error="boom", timestamp=TS),
                gen,
                _clock(),
            )
            # Worker should be retried (DispatchWorkerEffect emitted)
            assert len(effects) == 1
            assert isinstance(effects[0], DispatchWorkerEffect)
            assert effects[0].issue_id == "Q-1"

            # worker_active stays True for Q-1 (slot retained)
            assert state.issues["Q-1"].worker_active is True

            # Still exactly 3 active total
            active_now = [iid for iid in all_ids if state.issues[iid].worker_active]
            assert len(active_now) == 3

            # Queued issues should NOT have been promoted
            assert state.issues["Q-4"].worker_active is False
            assert state.issues["Q-5"].worker_active is False


class TestSequentialDrain:
    """10 issues through max_workers:3. Complete them one by one until all done."""

    def test_sequential_drain(self) -> None:
        config = parse_config(CAPPED_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        all_ids = [f"Q-{i}" for i in range(1, 11)]
        for iid in all_ids:
            state, _effects = reduce(
                config, state, CreateEvent(issue_id=iid, fields={"title": f"Issue {iid}"}, timestamp=TS), gen, _clock()
            )

        completed: list[str] = []
        while True:
            # Find an active issue to complete
            active_id = next(
                (iid for iid in all_ids if state.issues[iid].worker_active and state.issues[iid].state == "work"),
                None,
            )
            if active_id is None:
                break

            state, _effects = reduce(
                config,
                state,
                WorkerResultEvent(issue_id=active_id, result={"outcome": "done"}, timestamp=TS),
                gen,
                _clock(),
            )
            completed.append(active_id)

            # Invariant: at most 3 active at any time
            active_count = sum(
                1 for iid in all_ids if state.issues[iid].worker_active and state.issues[iid].state == "work"
            )
            assert active_count <= 3

        # All 10 should be done
        assert len(completed) == 10
        for iid in all_ids:
            assert state.issues[iid].state == "done"


class TestDecomposeFanoutRespectsMaxWorkers:
    """Create root, decompose into 5 children. Only 2 children active (max_workers:2)."""

    def test_decompose_fanout_respects_max_workers(self) -> None:
        config = parse_config(CAPPED_DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create root issue — initial state is "work" (active, max_workers:2), so dispatched
        state, effects = reduce(
            config,
            state,
            CreateEvent(issue_id="ROOT-1", fields={"title": "Root"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["ROOT-1"].worker_active is True
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)

        # Decompose into 5 children
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="ROOT-1",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": f"child-{i}", "fields": {"title": f"Child {i}"}} for i in range(1, 6)],
                },
                timestamp=TS,
            ),
            gen,
            _clock(),
        )

        # Root should no longer be active (it's decomposition-blocked)
        assert state.issues["ROOT-1"].worker_active is False

        # 5 children should have been created
        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "ROOT-1"]
        assert len(child_ids) == 5

        # Only 2 children should be active (max_workers:2)
        active_children = [iid for iid in child_ids if state.issues[iid].worker_active]
        queued_children = [iid for iid in child_ids if not state.issues[iid].worker_active]
        assert len(active_children) == 2
        assert len(queued_children) == 3

        # Dispatch effects should be exactly 2
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 2
