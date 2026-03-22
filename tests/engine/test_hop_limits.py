"""Tests for hop limit checks (max_visits, max_hops) in the reducer."""

from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    ErrorEffect,
    State,
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


# --- Config with max_visits on implementing ---

_LOOP_CONFIG_YAML = """\
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
    max_visits: 2
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

  done:
    terminal: true

initial: todo
"""

# --- Config with max_hops ---

_MAX_HOPS_CONFIG_YAML = """\
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

  done:
    terminal: true

initial: todo
max_hops: 3
"""


# --- Config with passive advance states and max_visits ---

_ADVANCE_CONFIG_YAML = """\
issue:
  fields:
    title:
      type: string
      description: Title

states:
  backlog:
    on:
      start: implementing

  implementing:
    max_visits: 2
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - complete
            - needs_review
          description: Outcome
    on:
      complete: done
      needs_review: review

  review:
    on:
      approve: done
      rework: implementing

  done:
    terminal: true

initial: backlog
"""


# --- Config with decompose and max_hops ---

_DECOMPOSE_CONFIG_YAML = """\
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

  done:
    terminal: true

initial: scoping
max_hops: 2
"""


# --- Config with max_workers + max_visits for backfill test ---

_CAPPED_CONFIG_YAML = """\
issue:
  fields:
    title:
      type: string
      description: Title

states:
  todo:
    max_workers: 1
    max_visits: 2
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
    max_visits: 1
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - reject
            - complete
          description: Outcome
    on:
      reject: todo
      complete: done

  done:
    terminal: true

initial: todo
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

  done:
    terminal: true

initial: todo
"""


# --- Config: implementing -> qa -> implementing loop with max_visits ---

_IMPL_QA_LOOP_YAML = """\
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
    max_visits: 3
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - submit
          description: Outcome
    on:
      submit: qa

  qa:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - pass
            - fail
          description: QA result
    on:
      pass: done
      fail: implementing

  done:
    terminal: true

initial: todo
"""


class TestMaxVisitsBlocksTransition:
    """State with max_visits:2 — visit twice OK, third time blocked."""

    def test_max_visits_blocks_transition(self) -> None:
        config = parse_config(_LOOP_CONFIG_YAML)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create -> todo (visit 1 for todo)
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "todo"

        # Worker result: start -> implementing (visit 1 for implementing)
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"
        assert state.issues["A"].visit_counts["implementing"] == 1

        # Worker result: reject -> todo (visit 2 for todo)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "reject"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "todo"

        # Worker result: start -> implementing (visit 2 for implementing) — should succeed
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"
        assert state.issues["A"].visit_counts["implementing"] == 2

        # Worker result: reject -> todo (visit 3 for todo)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "reject"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "todo"

        # Worker result: start -> implementing (visit 3) — BLOCKED by max_visits=2
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "todo"  # did not move
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "max_visits" in error_effects[0].message


class TestMaxHopsBlocksTransition:
    """Config max_hops:3 — 3 hops OK, fourth blocked."""

    def test_max_hops_blocks_transition(self) -> None:
        config = parse_config(_MAX_HOPS_CONFIG_YAML)
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


class TestMaxVisitsOnAdvance:
    """Advance checks max_visits too."""

    def test_max_visits_on_advance(self) -> None:
        config = parse_config(_ADVANCE_CONFIG_YAML)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create -> backlog (passive)
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "backlog"

        # Advance: backlog -> implementing (visit 1)
        state, _ = reduce(
            config,
            state,
            AdvanceEvent(issue_id="A", target_state="implementing", timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"

        # Worker result: needs_review -> review (passive)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "needs_review"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "review"

        # Advance: review -> implementing (visit 2)
        state, _ = reduce(
            config,
            state,
            AdvanceEvent(issue_id="A", target_state="implementing", timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"

        # Worker result: needs_review -> review
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "needs_review"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "review"

        # Advance: review -> implementing (visit 3) — BLOCKED by max_visits=2
        state, effects = reduce(
            config,
            state,
            AdvanceEvent(issue_id="A", target_state="implementing", timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "review"  # did not move
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "max_visits" in error_effects[0].message


class TestDecomposeIncrementsHopCount:
    """Verify hop_count increases on decompose."""

    def test_decompose_increments_hop_count(self) -> None:
        config = parse_config(_DECOMPOSE_CONFIG_YAML)
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
        config = parse_config(_DECOMPOSE_CONFIG_YAML)
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


class TestLimitFreesSlotAndBackfills:
    """In max_workers state, limit hit frees slot, queued issue dispatched."""

    def test_limit_frees_slot_and_backfills(self) -> None:
        config = parse_config(_CAPPED_CONFIG_YAML)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create A -> todo, dispatched (slot used)
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "A"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].worker_active is True

        # Create B -> todo, queued (slot full)
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="B", fields={"title": "B"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["B"].worker_active is False

        # A: todo -> implementing (frees todo slot, B should get dispatched)
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"
        assert state.issues["B"].worker_active is True  # backfilled

        # A: implementing -> todo (reject), visit 2 for todo
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "reject"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        # B still has the slot, A queued
        assert state.issues["A"].state == "todo"

        # B: todo -> implementing
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="B", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        # Now A should be dispatched in todo
        assert state.issues["A"].worker_active is True

        # A: todo -> implementing — BLOCKED by max_visits=1 on implementing
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "todo"  # did not move
        assert state.issues["A"].worker_active is False  # slot freed
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "max_visits" in error_effects[0].message


class TestLimitLogsLimitReached:
    """Verify log entry type and data on limit."""

    def test_limit_logs_limit_reached(self) -> None:
        config = parse_config(_LOOP_CONFIG_YAML)
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

        # Visit implementing twice
        for _ in range(2):
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

        # Third attempt triggers limit
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        log = state.issues["A"].event_log
        limit_entries = [e for e in log if e.type == "limit_reached"]
        assert len(limit_entries) == 1
        entry = limit_entries[0]
        assert entry.data["limit"] == "max_visits"
        assert entry.data["state"] == "implementing"
        assert entry.data["count"] == 3


class TestNoLimitByDefault:
    """Without max_visits/max_hops, loops run freely."""

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


class TestLoopDetectionImplementingQa:
    """implementing -> qa -> implementing loop with max_visits:3 on implementing."""

    def test_loop_detection_implementing_qa(self) -> None:
        config = parse_config(_IMPL_QA_LOOP_YAML)
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

        # todo -> implementing (visit 1)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].visit_counts["implementing"] == 1

        # implementing -> qa
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "submit"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # qa -> implementing (visit 2)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "fail"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].visit_counts["implementing"] == 2

        # implementing -> qa
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "submit"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # qa -> implementing (visit 3)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "fail"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].visit_counts["implementing"] == 3

        # implementing -> qa
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "submit"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # qa -> implementing (visit 4) — BLOCKED by max_visits=3
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "fail"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "qa"  # did not move
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "max_visits" in error_effects[0].message


class TestDecomposeLoopDetection:
    """Parent decomposes, child completes, parent unblocks, decomposes again — max_hops stops it."""

    def test_decompose_loop_detection(self) -> None:
        config = parse_config(_DECOMPOSE_CONFIG_YAML)
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
