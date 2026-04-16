"""Tests for hop limit checks (max_hops) in the reducer."""

from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    ErrorEffect,
    State,
    StateMachineConfig,
    WorkerResultEvent,
)


def _clock(v: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: v


def _counter() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


# --- Base config WITHOUT max_hops (set via constructor override) ---

_BASE_CONFIG_YAML = """\
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
          values:
            - start
          description: Decision
    on:
      start: implementing

  implementing:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - complete
            - reject
          description: Outcome
    on:
      complete: done
      reject: todo


initial: todo
"""


# --- Config with decompose (max_hops set via constructor) ---

_DECOMPOSE_BASE_YAML = """\
issue:
  fields:
    title:
      type: string
      description: Title

states:
  scoping:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - decompose
            - complete
          description: Decision
        sub_issues:
          type: list
          items: "$issue"
          description: Sub-issues
          required_when:
            - decompose
    on:
      decompose:
        action: decompose
      complete: done


initial: scoping
"""


# --- Config with no limits ---

_NO_LIMIT_CONFIG_YAML = """\
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
          values:
            - start
          description: Decision
    on:
      start: implementing

  implementing:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - complete
            - reject
          description: Outcome
    on:
      complete: done
      reject: todo


initial: todo
"""


def _config_with_max_hops(yaml_str: str, max_hops: int) -> StateMachineConfig:
    """Parse config from YAML and set max_hops via object.__setattr__."""
    config = parse_config(yaml_str)
    object.__setattr__(config, "max_hops", max_hops)
    return config


class TestMaxHopsBlocksTransition:
    """Config max_hops:3 — 3 hops OK, fourth blocked."""

    def test_max_hops_blocks_transition(self) -> None:
        config = _config_with_max_hops(_BASE_CONFIG_YAML, max_hops=3)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create -> todo (hop_count = 0)
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Hop 1: todo -> implementing
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].hop_count == 1

        # Hop 2: implementing -> todo (reject)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "reject"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].hop_count == 2

        # Hop 3: todo -> implementing
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].hop_count == 3

        # Hop 4: implementing -> todo — BLOCKED by max_hops=3
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "reject"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"  # did not move
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "max_hops" in error_effects[0].message


class TestDecomposeIncrementsHopCount:
    """Verify hop_count increases on decompose."""

    def test_decompose_increments_hop_count(self) -> None:
        config = _config_with_max_hops(_DECOMPOSE_BASE_YAML, max_hops=2)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create -> scoping
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["P"].hop_count == 0

        # Decompose
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        assert state.issues["P"].hop_count == 1


class TestMaxHopsBlocksDecompose:
    """Decompose blocked by max_hops."""

    def test_max_hops_blocks_decompose(self) -> None:
        config = _config_with_max_hops(_DECOMPOSE_BASE_YAML, max_hops=2)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create -> scoping (hop_count=0)
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Decompose 1: hop_count -> 1
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        assert state.issues["P"].hop_count == 1

        # Complete child so parent unblocks
        child_id = "GEN-1"
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=child_id, result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Decompose 2: hop_count -> 2
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c2", "fields": {"title": "C2"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        assert state.issues["P"].hop_count == 2

        # Complete second child
        child_id2 = "GEN-2"
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=child_id2, result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Decompose 3: hop_count would be 3, max_hops=2 -> BLOCKED
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c3", "fields": {"title": "C3"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        assert state.issues["P"].hop_count == 2  # did not increment
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "max_hops" in error_effects[0].message


class TestNoLimitByDefault:
    """Without max_hops, loops run freely."""

    def test_no_limit_by_default(self) -> None:
        config = parse_config(_NO_LIMIT_CONFIG_YAML)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create -> todo
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Loop 10 times: todo -> implementing -> todo
        for _ in range(10):
            state, _ = reduce(
                config,
                state,
                WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
                gen,
                _clock(),
            )
            state, _ = reduce(
                config,
                state,
                WorkerResultEvent(issue_id="A", result={"outcome": "reject"}, timestamp="2026-01-01T00:00:00Z"),
                gen,
                _clock(),
            )

        # Should still be running fine
        assert state.issues["A"].state == "todo"
        assert state.issues["A"].visit_counts["implementing"] == 10
        assert state.issues["A"].hop_count == 20
        # No error effects during the loop
        limit_entries = [e for e in state.issues["A"].event_log if e.type == "limit_reached"]
        assert len(limit_entries) == 0


class TestDecomposeLoopDetection:
    """Parent decomposes, child completes, parent unblocks, decomposes again — max_hops stops it."""

    def test_decompose_loop_detection(self) -> None:
        config = _config_with_max_hops(_DECOMPOSE_BASE_YAML, max_hops=2)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create parent -> scoping
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Decompose 1 (hop 1)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        assert state.issues["P"].hop_count == 1

        # Complete child 1
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="GEN-1", result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Decompose 2 (hop 2) — should succeed (max_hops=2)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c2", "fields": {"title": "C2"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        assert state.issues["P"].hop_count == 2

        # Complete child 2
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="GEN-2", result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Decompose 3 (hop 3) — BLOCKED by max_hops=2
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c3", "fields": {"title": "C3"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        assert state.issues["P"].hop_count == 2  # unchanged
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "max_hops" in error_effects[0].message
