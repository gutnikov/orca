"""CI/CD pipeline scenario tests with merge serialization (max_workers: 1)."""

from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    State,
    WorkerFailedEvent,
    WorkerResultEvent,
)

PIPELINE_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
initial: todo
states:
  todo: {}
  implementing:
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
      done: qa
  qa:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values: [passed, failed]
          description: "QA"
          values_description:
            passed: "Pass"
            failed: "Fail"
    on:
      passed: apply
      failed: implementing
  apply:
    max_workers: 1
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values: [merged, conflict]
          description: "Merge"
          values_description:
            merged: "OK"
            conflict: "Conflict"
    on:
      merged: done
      conflict: implementing
"""

TS = "2026-01-01T00:00:00Z"


def _clock(value: str = TS) -> Callable[[], str]:
    return lambda: value


def _counter() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def _empty_state() -> State:
    return State(issues={}, worker_queues={})


def _advance_to_apply(config: object, state: State, issue_id: str, gen: Callable[[], str]) -> State:
    """Helper to advance an issue from todo through implementing and qa to apply."""
    from orca.engine.types import StateMachineConfig

    assert isinstance(config, StateMachineConfig)
    state, _ = reduce(
        config, state, AdvanceEvent(issue_id=issue_id, target_state="implementing", timestamp=TS), gen, _clock()
    )
    state, _ = reduce(
        config, state, WorkerResultEvent(issue_id=issue_id, result={"outcome": "done"}, timestamp=TS), gen, _clock()
    )
    state, _ = reduce(
        config, state, WorkerResultEvent(issue_id=issue_id, result={"outcome": "passed"}, timestamp=TS), gen, _clock()
    )
    return state


class TestSerializedMerge4Issues:
    """4 issues pass qa, enter apply. Only first active, rest queued."""

    def test_serialized_merge_4_issues(self) -> None:
        config = parse_config(PIPELINE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        ids = [f"P-{i}" for i in range(1, 5)]

        # Create all issues
        for iid in ids:
            state, _ = reduce(
                config, state, CreateEvent(issue_id=iid, fields={"title": iid}, timestamp=TS), gen, _clock()
            )

        # Advance all to apply
        for iid in ids:
            state = _advance_to_apply(config, state, iid, gen)

        # First issue should be active, rest queued
        assert state.issues["P-1"].state == "apply"
        assert state.issues["P-1"].worker_active is True
        for iid in ids[1:]:
            assert state.issues[iid].state == "apply"
            assert state.issues[iid].worker_active is False

        # Queue should contain P-2, P-3, P-4
        assert state.worker_queues.get("default:apply") == ["P-2", "P-3", "P-4"]

        # Merge them one by one
        for i, iid in enumerate(ids):
            state, effects = reduce(
                config,
                state,
                WorkerResultEvent(issue_id=iid, result={"outcome": "merged"}, timestamp=TS),
                gen,
                _clock(),
            )
            assert state.issues[iid].state == "done"

            if i < len(ids) - 1:
                # Backfill: next issue should get dispatched
                next_id = ids[i + 1]
                dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
                assert len(dispatch_effects) == 1
                assert dispatch_effects[0].issue_id == next_id
                assert dispatch_effects[0].state == "apply"
                assert state.issues[next_id].worker_active is True
            else:
                # Last one, no backfill
                dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
                assert len(dispatch_effects) == 0

        # All done
        for iid in ids:
            assert state.issues[iid].state == "done"


class TestConflictFreesSlotForNext:
    """2 issues in apply, first conflicts → second gets the slot."""

    def test_conflict_frees_slot_for_next(self) -> None:
        config = parse_config(PIPELINE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        for iid in ["P-1", "P-2"]:
            state, _ = reduce(
                config, state, CreateEvent(issue_id=iid, fields={"title": iid}, timestamp=TS), gen, _clock()
            )
            state = _advance_to_apply(config, state, iid, gen)

        assert state.issues["P-1"].worker_active is True
        assert state.issues["P-2"].worker_active is False
        assert state.worker_queues.get("default:apply") == ["P-2"]

        # P-1 conflicts → goes back to implementing, P-2 gets dispatched in apply
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P-1", result={"outcome": "conflict"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["P-1"].state == "implementing"
        assert state.issues["P-1"].worker_active is True  # implementing dispatches immediately

        # P-2 should be dispatched in apply
        apply_dispatches = [e for e in effects if isinstance(e, DispatchWorkerEffect) and e.state == "apply"]
        assert len(apply_dispatches) == 1
        assert apply_dispatches[0].issue_id == "P-2"
        assert state.issues["P-2"].worker_active is True


class TestConflictReenterAtBackOfQueue:
    """3 issues. First conflicts, re-enters at back of queue."""

    def test_conflict_reenter_at_back_of_queue(self) -> None:
        config = parse_config(PIPELINE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        for iid in ["P-1", "P-2", "P-3"]:
            state, _ = reduce(
                config, state, CreateEvent(issue_id=iid, fields={"title": iid}, timestamp=TS), gen, _clock()
            )
            state = _advance_to_apply(config, state, iid, gen)

        assert state.issues["P-1"].worker_active is True
        assert state.worker_queues.get("default:apply") == ["P-2", "P-3"]

        # P-1 conflicts → goes back to implementing
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P-1", result={"outcome": "conflict"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["P-1"].state == "implementing"

        # P-2 should now be active in apply
        assert state.issues["P-2"].worker_active is True
        assert state.issues["P-2"].state == "apply"

        # Queue should now be just P-3
        assert state.worker_queues.get("default:apply") == ["P-3"]

        # P-1 goes back through implementing→qa→apply, should end up queued behind P-3
        state, _ = reduce(
            config, state, WorkerResultEvent(issue_id="P-1", result={"outcome": "done"}, timestamp=TS), gen, _clock()
        )
        state, _ = reduce(
            config, state, WorkerResultEvent(issue_id="P-1", result={"outcome": "passed"}, timestamp=TS), gen, _clock()
        )

        assert state.issues["P-1"].state == "apply"
        assert state.issues["P-1"].worker_active is False
        assert state.worker_queues.get("default:apply") == ["P-3", "P-1"]


class TestWorkerFailedRetainsSlot:
    """WorkerFailed on apply retains slot, queued issue stays queued."""

    def test_worker_failed_retains_slot(self) -> None:
        config = parse_config(PIPELINE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        for iid in ["P-1", "P-2"]:
            state, _ = reduce(
                config, state, CreateEvent(issue_id=iid, fields={"title": iid}, timestamp=TS), gen, _clock()
            )
            state = _advance_to_apply(config, state, iid, gen)

        assert state.issues["P-1"].worker_active is True
        assert state.worker_queues.get("default:apply") == ["P-2"]

        # Worker fails on P-1 → slot retained, P-2 stays queued
        state, effects = reduce(
            config, state, WorkerFailedEvent(issue_id="P-1", error="timeout", timestamp=TS), gen, _clock()
        )
        assert state.issues["P-1"].worker_active is True  # slot retained
        assert state.issues["P-1"].state == "apply"

        # Should get a re-dispatch effect for P-1
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "P-1"
        assert effects[0].state == "apply"

        # P-2 should still be queued
        assert state.issues["P-2"].worker_active is False
        assert state.worker_queues.get("default:apply") == ["P-2"]
