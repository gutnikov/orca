"""Regression tests for verified engine bugs.

Covers:
1. `failed` as a transition/advance target must not raise KeyError.
2. Decompose sub_issues payload is validated atomically before any mutation.
3. `outcome -> failed` retry path must not exceed max_workers.
4. Unrouted outcome releases the worker slot instead of wedging the issue.
5. `max_hops:` / `max_worker_retries:` are parsed from workflow YAML.
6. Unknown debug action mutates nothing.
7. Decompose with `then` counts as a single hop.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from orca.engine.config import ConfigValidationError, parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DebugDecisionEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    InlineComment,
    Issue,
    State,
    StateMachineConfig,
    WorkerResultEvent,
)

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


# --- Fix 1: `failed` target must not crash with KeyError ---

_PASSIVE_CONFIG_YAML = """\
issue:
  fields:
    title:
      type: string
      description: Title

states:
  backlog: {}

initial: backlog
"""

_DECOMPOSE_THEN_FAILED_YAML = """\
root_type: epic
types:
  epic:
    fields:
      title: {type: string, description: Title}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/default.md
          result_format:
            outcome:
              type: enum
              values: [decompose, complete]
              description: Decision
            sub_issues:
              type: list
              items: "$issue"
              description: Sub-issues
              required_when: [decompose]
        on:
          decompose:
            action: decompose
            child_type: task
            then: failed
          complete: done
  task:
    fields:
      title: {type: string, description: Title}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/default.md
          result_format:
            outcome:
              type: enum
              values: [done]
              description: Outcome
        on:
          done: done
"""


class TestFailedTargetNoKeyError:
    def test_advance_to_failed_does_not_raise(self) -> None:
        config = parse_config(_PASSIVE_CONFIG_YAML)
        state = _empty_state()
        gen = _counter()

        state, _ = reduce(config, state, CreateEvent(issue_id="A", fields={"title": "T"}, timestamp=TS), gen, _clock())
        assert state.issues["A"].state == "backlog"

        state, effects = reduce(
            config,
            state,
            AdvanceEvent(issue_id="A", target_state="failed", timestamp=TS),
            gen,
            _clock(),
        )

        # No crash; issue is marked failed, no errors, no dispatch
        assert state.issues["A"].state == "failed"
        assert [e for e in effects if isinstance(e, ErrorEffect)] == []
        assert [e for e in effects if isinstance(e, DispatchWorkerEffect)] == []

    def test_decompose_then_failed_does_not_raise(self) -> None:
        config = parse_config(_DECOMPOSE_THEN_FAILED_YAML)
        state = _empty_state()
        gen = _counter()

        state, _ = reduce(
            config, state, CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp=TS), gen, _clock()
        )

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={"outcome": "decompose", "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}]},
                timestamp=TS,
            ),
            gen,
            _clock(),
        )

        # Parent transitioned to the built-in failed state without crashing
        assert state.issues["P"].state == "failed"
        assert [e for e in effects if isinstance(e, ErrorEffect)] == []
        # Child still created and dispatched
        children = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "P"]
        assert len(children) == 1
        assert state.issues[children[0]].worker_active is True


# --- Fix 2: sub_issues payload validated atomically ---

_DECOMPOSE_NO_DEFAULT_TYPE_YAML = """\
root_type: epic
types:
  epic:
    fields:
      title: {type: string, description: Title}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/default.md
          result_format:
            outcome:
              type: enum
              values: [decompose, complete]
              description: Decision
            sub_issues:
              type: list
              items: "$issue"
              description: Sub-issues
              required_when: [decompose]
        on:
          decompose:
            action: decompose
          complete: done
  task:
    fields:
      title: {type: string, description: Title}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/default.md
          result_format:
            outcome:
              type: enum
              values: [done]
              description: Outcome
        on:
          done: done
"""


class TestDecomposePayloadValidation:
    def _scoping_state(self, config: StateMachineConfig) -> tuple[State, Callable[[], str]]:
        state = _empty_state()
        gen = _counter()
        state, _ = reduce(
            config, state, CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp=TS), gen, _clock()
        )
        return state, gen

    def _decompose(
        self, config: StateMachineConfig, state: State, gen: Callable[[], str], sub_issues: list[object]
    ) -> tuple[State, list[object]]:
        return reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "decompose", "sub_issues": sub_issues}, timestamp=TS),
            gen,
            _clock(),
        )

    def _assert_rejected_and_nothing_created(self, state: State, effects: list[object]) -> None:
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        # No children created at all (no partial creation)
        children = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "P"]
        assert children == []
        # Parent untouched
        assert state.issues["P"].state == "scoping"
        assert state.issues["P"].hop_count == 0

    def test_duplicate_keys_rejected(self) -> None:
        config = parse_config(_DECOMPOSE_NO_DEFAULT_TYPE_YAML)
        state, gen = self._scoping_state(config)
        state, effects = self._decompose(
            config,
            state,
            gen,
            [
                {"key": "c1", "type": "task", "fields": {"title": "C1"}},
                {"key": "c1", "type": "task", "fields": {"title": "C2"}},
            ],
        )
        self._assert_rejected_and_nothing_created(state, effects)

    def test_missing_key_rejected(self) -> None:
        config = parse_config(_DECOMPOSE_NO_DEFAULT_TYPE_YAML)
        state, gen = self._scoping_state(config)
        state, effects = self._decompose(
            config,
            state,
            gen,
            [{"type": "task", "fields": {"title": "C1"}}],
        )
        self._assert_rejected_and_nothing_created(state, effects)

    def test_non_dict_entry_rejected(self) -> None:
        config = parse_config(_DECOMPOSE_NO_DEFAULT_TYPE_YAML)
        state, gen = self._scoping_state(config)
        state, effects = self._decompose(config, state, gen, ["not-a-dict"])
        self._assert_rejected_and_nothing_created(state, effects)

    def test_bad_type_on_second_child_creates_nothing(self) -> None:
        """A bad entry mid-list must not leave earlier children orphaned in state."""
        config = parse_config(_DECOMPOSE_NO_DEFAULT_TYPE_YAML)
        state, gen = self._scoping_state(config)
        state, effects = self._decompose(
            config,
            state,
            gen,
            [
                {"key": "c1", "type": "task", "fields": {"title": "C1"}},
                {"key": "c2", "type": "bogus", "fields": {"title": "C2"}},
            ],
        )
        self._assert_rejected_and_nothing_created(state, effects)

    def test_missing_type_without_rule_default_creates_nothing(self) -> None:
        config = parse_config(_DECOMPOSE_NO_DEFAULT_TYPE_YAML)
        state, gen = self._scoping_state(config)
        state, effects = self._decompose(
            config,
            state,
            gen,
            [
                {"key": "c1", "type": "task", "fields": {"title": "C1"}},
                {"key": "c2", "fields": {"title": "C2"}},
            ],
        )
        self._assert_rejected_and_nothing_created(state, effects)

    def test_valid_payload_still_creates_children(self) -> None:
        config = parse_config(_DECOMPOSE_NO_DEFAULT_TYPE_YAML)
        state, gen = self._scoping_state(config)
        state, effects = self._decompose(
            config,
            state,
            gen,
            [
                {"key": "c1", "type": "task", "fields": {"title": "C1"}},
                {"key": "c2", "type": "task", "fields": {"title": "C2"}},
            ],
        )
        assert [e for e in effects if isinstance(e, ErrorEffect)] == []
        children = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "P"]
        assert len(children) == 2


# --- Fix 3: outcome -> failed retry must retain the slot (max_workers) ---

_FAILED_MAX_WORKERS_YAML = """\
issue:
  fields:
    title:
      type: string
      description: Title

states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values: [start]
          description: Decision
    on:
      start: apply

  apply:
    max_workers: 1
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values: [applied, fail]
          description: Apply result
        reason:
          type: string
          description: Failure reason
          required_when: fail
    on:
      applied: done
      fail: failed

initial: todo
"""


def _two_issues_in_apply(config: StateMachineConfig) -> tuple[State, Callable[[], str]]:
    """Create A and B; A active in apply (max_workers=1), B queued."""
    state = _empty_state()
    gen = _counter()
    for iid in ("A", "B"):
        state, _ = reduce(config, state, CreateEvent(issue_id=iid, fields={"title": iid}, timestamp=TS), gen, _clock())
        state, _ = reduce(
            config, state, WorkerResultEvent(issue_id=iid, result={"outcome": "start"}, timestamp=TS), gen, _clock()
        )
    assert state.issues["A"].worker_active is True
    assert state.issues["B"].worker_active is False
    assert state.worker_queues.get("default:apply") == ["B"]
    return state, gen


class TestFailedOutcomeRetryRespectsMaxWorkers:
    def test_retry_retains_slot(self) -> None:
        config = parse_config(_FAILED_MAX_WORKERS_YAML)
        object.__setattr__(config, "max_worker_retries", 3)
        state, gen = _two_issues_in_apply(config)

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "fail", "reason": "boom"}, timestamp=TS),
            gen,
            _clock(),
        )

        # A retried in place — slot retained
        assert state.issues["A"].worker_active is True
        dispatched = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert [e.issue_id for e in dispatched] == ["A"]
        # B must NOT have been backfilled into the slot
        assert state.issues["B"].worker_active is False
        assert state.worker_queues.get("default:apply") == ["B"]
        # Never more than max_workers active in apply
        active = [iid for iid, iss in state.issues.items() if iss.state == "apply" and iss.worker_active]
        assert active == ["A"]

    def test_exhausted_retries_release_slot_and_backfill(self) -> None:
        config = parse_config(_FAILED_MAX_WORKERS_YAML)
        object.__setattr__(config, "max_worker_retries", 1)
        state, gen = _two_issues_in_apply(config)

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "fail", "reason": "boom"}, timestamp=TS),
            gen,
            _clock(),
        )

        # A gave up — slot released
        assert state.issues["A"].worker_active is False
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "retries exhausted" in error_effects[0].message
        # B backfilled into the freed slot
        assert state.issues["B"].worker_active is True
        dispatched = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert [e.issue_id for e in dispatched] == ["B"]


# --- Fix 4: unrouted outcome releases the slot instead of wedging ---


class TestUnroutedOutcomeReleasesSlot:
    def test_slot_released_on_unrouted_outcome(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = _empty_state()
        gen = _counter()

        state, _ = reduce(config, state, CreateEvent(issue_id="A", fields={"title": "T"}, timestamp=TS), gen, _clock())
        assert state.issues["A"].worker_active is True

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "nonexistent"}, timestamp=TS),
            gen,
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        # Slot released — the worker process has already exited
        assert state.issues["A"].worker_active is False
        assert state.issues["A"].state == "todo"

    def test_backfill_after_unrouted_outcome(self) -> None:
        config = parse_config(_FAILED_MAX_WORKERS_YAML)
        state, gen = _two_issues_in_apply(config)

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "garbage"}, timestamp=TS),
            gen,
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert state.issues["A"].worker_active is False
        # B backfilled into the freed slot
        assert state.issues["B"].worker_active is True
        dispatched = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert [e.issue_id for e in dispatched] == ["B"]


# --- Fix 5: max_hops / max_worker_retries parsed from YAML ---

_LEGACY_LIMITS_YAML = """\
issue:
  fields:
    title:
      type: string
      description: Title

states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done

initial: todo
max_hops: 7
max_worker_retries: 4
"""

_TYPED_LIMITS_YAML = """\
root_type: task
max_hops: 15
max_worker_retries: 2
types:
  task:
    fields:
      title: {type: string, description: Title}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/default.md
          result_format:
            outcome:
              type: enum
              values: [done]
              description: d
        on:
          done: done
"""


class TestLimitsParsedFromYaml:
    def test_legacy_config_parses_limits(self) -> None:
        cfg = parse_config(_LEGACY_LIMITS_YAML)
        assert cfg.max_hops == 7
        assert cfg.max_worker_retries == 4

    def test_typed_config_parses_limits(self) -> None:
        cfg = parse_config(_TYPED_LIMITS_YAML)
        assert cfg.max_hops == 15
        assert cfg.max_worker_retries == 2

    def test_limits_default_to_none(self) -> None:
        cfg = parse_config(_LEGACY_LIMITS_YAML.replace("max_hops: 7\n", "").replace("max_worker_retries: 4\n", ""))
        assert cfg.max_hops is None
        assert cfg.max_worker_retries is None

    def test_invalid_max_hops_rejected(self) -> None:
        with pytest.raises(ConfigValidationError, match="max_hops"):
            parse_config(_LEGACY_LIMITS_YAML.replace("max_hops: 7", "max_hops: 0"))

    def test_invalid_max_worker_retries_rejected(self) -> None:
        with pytest.raises(ConfigValidationError, match="max_worker_retries"):
            parse_config(_LEGACY_LIMITS_YAML.replace("max_worker_retries: 4", "max_worker_retries: 0"))


# --- Fix 6: unknown debug action must mutate nothing ---


class TestUnknownDebugActionMutatesNothing:
    def test_comments_preserved_on_unknown_action(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        comment = InlineComment(id="c1", file="f.py", line=1, body="note", created_at=TS, updated_at=TS)
        issue = Issue(
            type="default",
            fields={"title": "T"},
            state="todo",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
            debug_pending=True,
            inline_comments=[comment],
        )
        state = State(issues={"A": issue}, worker_queues={})

        new_state, effects = reduce(
            config,
            state,
            DebugDecisionEvent(issue_id="A", action="bogus", comments=[], timestamp=TS),
            _counter(),
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "bogus" in error_effects[0].message
        # Nothing mutated: comments retained, no debug_decision logged, still pending
        new_issue = new_state.issues["A"]
        assert len(new_issue.inline_comments) == 1
        assert new_issue.inline_comments[0].body == "note"
        assert [e for e in new_issue.event_log if e.type == "debug_decision"] == []
        assert new_issue.debug_pending is True


# --- Fix 7: decompose with `then` counts as one hop ---

_DECOMPOSE_THEN_YAML = """\
root_type: epic
types:
  epic:
    fields:
      title: {type: string, description: Title}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/default.md
          result_format:
            outcome:
              type: enum
              values: [decompose, complete]
              description: Decision
            sub_issues:
              type: list
              items: "$issue"
              description: Sub-issues
              required_when: [decompose]
        on:
          decompose:
            action: decompose
            child_type: task
            then: waiting
          complete: done
      waiting: {}
  task:
    fields:
      title: {type: string, description: Title}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/default.md
          result_format:
            outcome:
              type: enum
              values: [done]
              description: Outcome
        on:
          done: done
"""


class TestDecomposeWithThenSingleHop:
    def test_decompose_then_counts_one_hop(self) -> None:
        config = parse_config(_DECOMPOSE_THEN_YAML)
        state = _empty_state()
        gen = _counter()

        state, _ = reduce(
            config, state, CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp=TS), gen, _clock()
        )
        assert state.issues["P"].hop_count == 0

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={"outcome": "decompose", "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}]},
                timestamp=TS,
            ),
            gen,
            _clock(),
        )

        assert state.issues["P"].state == "waiting"
        assert state.issues["P"].hop_count == 1

    def test_decompose_then_does_not_overshoot_max_hops(self) -> None:
        config = parse_config(_DECOMPOSE_THEN_YAML)
        object.__setattr__(config, "max_hops", 1)
        state = _empty_state()
        gen = _counter()

        state, _ = reduce(
            config, state, CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp=TS), gen, _clock()
        )

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={"outcome": "decompose", "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}]},
                timestamp=TS,
            ),
            gen,
            _clock(),
        )

        # One logical step costs exactly one hop — allowed by max_hops=1
        assert [e for e in effects if isinstance(e, ErrorEffect)] == []
        assert state.issues["P"].state == "waiting"
        assert state.issues["P"].hop_count == 1
