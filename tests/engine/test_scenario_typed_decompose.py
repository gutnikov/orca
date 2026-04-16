"""Typed decomposition scenario: epic -> task with different flows."""

from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
    WorkerResultEvent,
)

TYPED_CONFIG = """\
root_type: epic
max_hops: 20

types:
  epic:
    fields:
      title: {type: string, description: Title}
      scope: {type: string, description: Scope}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scope.md
          result_format:
            outcome:
              type: enum
              values: [ready, decompose]
              description: d
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
              description: s
        on:
          ready: done
          decompose:
            action: decompose
            child_type: task
            then: done

  task:
    fields:
      title: {type: string, description: Title}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/impl.md
          result_format:
            outcome:
              type: enum
              values: [done]
              description: d
        on:
          done: done
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


class TestTypedDecomposition:
    def test_epic_decomposes_into_tasks_with_different_flow(self) -> None:
        config = parse_config(TYPED_CONFIG)
        gen = _counter()
        state = State(issues={}, worker_queues={})

        # Create epic — starts in scoping
        state, effects = reduce(
            config,
            state,
            CreateEvent(issue_id="EPIC-1", fields={"title": "Big feature", "scope": "all"}, timestamp=TS),
            gen,
            _clock(),
        )
        assert state.issues["EPIC-1"].type == "epic"
        assert state.issues["EPIC-1"].state == "scoping"
        dispatches = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatches) == 1
        assert dispatches[0].issue_type == "epic"

        # Epic decomposes into 2 tasks
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="EPIC-1",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "api", "fields": {"title": "Build API"}},
                        {"key": "ui", "fields": {"title": "Build UI"}},
                    ],
                },
                timestamp=TS,
            ),
            gen,
            _clock(),
        )

        # Epic transitions to done via `then: done`
        assert state.issues["EPIC-1"].state == "done"

        # Children are TASKS starting at IMPLEMENTING (not scoping!)
        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "EPIC-1"]
        assert len(child_ids) == 2
        for cid in child_ids:
            assert state.issues[cid].type == "task"
            assert state.issues[cid].state == "implementing"
            assert state.issues[cid].worker_active is True

        # Dispatch effects should have issue_type="task"
        task_dispatches = [e for e in effects if isinstance(e, DispatchWorkerEffect) and e.issue_id in child_ids]
        for d in task_dispatches:
            assert d.issue_type == "task"

        # Complete both tasks
        for cid in child_ids:
            state, _ = reduce(
                config,
                state,
                WorkerResultEvent(issue_id=cid, result={"outcome": "done"}, timestamp=TS),
                gen,
                _clock(),
            )
            assert state.issues[cid].state == "done"

    def test_worker_overrides_child_type(self) -> None:
        config = parse_config(TYPED_CONFIG)
        gen = _counter()
        state = State(issues={}, worker_queues={})

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="EPIC-1", fields={"title": "Feature", "scope": "all"}, timestamp=TS),
            gen,
            _clock(),
        )

        # Worker overrides one child to be an epic (recursive decomposition)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="EPIC-1",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "sub-epic", "type": "epic", "fields": {"title": "Sub-epic", "scope": "sub"}},
                        {"key": "task", "fields": {"title": "Simple task"}},
                    ],
                },
                timestamp=TS,
            ),
            gen,
            _clock(),
        )

        children = {
            state.issues[iid].fields["title"]: state.issues[iid]
            for iid in state.issues
            if state.issues[iid].decomposed_from == "EPIC-1"
        }
        # Sub-epic starts in scoping (epic flow)
        assert children["Sub-epic"].type == "epic"
        assert children["Sub-epic"].state == "scoping"
        # Simple task starts in implementing (task flow)
        assert children["Simple task"].type == "task"
        assert children["Simple task"].state == "implementing"

    def test_missing_child_type_errors(self) -> None:
        """If decompose rule has no child_type and worker doesn't specify, error."""
        no_child_type_config = """\
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
          prompt: p.md
          result_format:
            outcome:
              type: enum
              values: [decompose]
              description: d
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
              description: s
        on:
          decompose:
            action: decompose
"""
        config = parse_config(no_child_type_config)
        gen = _counter()
        state = State(issues={}, worker_queues={})

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="E1", fields={"title": "X"}, timestamp=TS),
            gen,
            _clock(),
        )

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="E1",
                result={"outcome": "decompose", "sub_issues": [{"key": "a", "fields": {"title": "A"}}]},
                timestamp=TS,
            ),
            gen,
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) >= 1
        assert "type" in error_effects[0].message.lower() or "child_type" in error_effects[0].message.lower()

    def test_unknown_child_type_errors(self) -> None:
        """If worker specifies a type that doesn't exist, error."""
        config = parse_config(TYPED_CONFIG)
        gen = _counter()
        state = State(issues={}, worker_queues={})

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="E1", fields={"title": "X", "scope": "all"}, timestamp=TS),
            gen,
            _clock(),
        )

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="E1",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "a", "type": "nonexistent", "fields": {"title": "A"}}],
                },
                timestamp=TS,
            ),
            gen,
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) >= 1
        assert "nonexistent" in error_effects[0].message
