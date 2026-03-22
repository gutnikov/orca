# State Machine Engine — Test Scenarios Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Comprehensive test coverage for the state machine engine, covering real-world workflows, edge cases, and error conditions beyond the basic happy-path tests in the implementation plan.

**Architecture:** All tests exercise the public API (`reduce`, `parse_config`, `State`, events). Tests use deterministic ID generators and build state step-by-step through event sequences. No mocking — the reducer is pure.

**Tech Stack:** Python 3.12, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-state-machine-engine-design.md`
**Implementation Plan:** `docs/superpowers/plans/2026-03-22-state-machine-engine.md`

**Prerequisite:** All tasks from the implementation plan must be completed first.

---

## File Structure

```
tests/engine/
├── test_scenario_kanban.py           — classic kanban workflow
├── test_scenario_pipeline.py         — CI/CD merge serialization
├── test_scenario_decompose.py        — decomposition and unblock patterns
├── test_scenario_queuing.py          — max_workers stress patterns
├── test_scenario_edge_cases.py       — boundary and error conditions
├── test_scenario_serialization.py    — state round-trip and persistence
```

---

### Task 1: Classic Kanban Workflow

**Files:**
- Create: `tests/engine/test_scenario_kanban.py`

Tests a typical `todo → implementing → review → done` pipeline with loops.

- [ ] **Step 1: Write test — full happy path through 3 active states**

An issue goes `todo → implementing → review → done` without any loops. Verify state, result_history, and effects at each step.

```python
# tests/engine/test_scenario_kanban.py
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    State,
    WorkerResultEvent,
)

KANBAN_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: "Title"
    text:
      type: string
      description: "Description"

initial: todo

states:
  todo: {}

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Implementation result"
          values_description:
            done: "Implementation complete"
        summary:
          type: string
          description: "What was done"
    on:
      done: review

  review:
    worker:
      result_format:
        outcome:
          type: enum
          values: [approved, rejected]
          description: "Review result"
          values_description:
            approved: "Code approved"
            rejected: "Changes requested"
        feedback:
          type: string
          description: "Review feedback"
    on:
      approved: done
      rejected: implementing

  done:
    terminal: true
"""


def _counter() -> Callable[[], str]:
    n = 0
    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"
    return gen


def test_full_happy_path() -> None:
    config = parse_config(KANBAN_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    # Create
    state, effects = reduce(config, state, CreateEvent(issue_id="K-1", fields={"title": "Feature", "text": "Build it"}), gen)
    assert state.issues["K-1"].state == "todo"
    assert len(effects) == 0

    # Advance to implementing
    state, effects = reduce(config, state, AdvanceEvent(issue_id="K-1", target_state="implementing"), gen)
    assert state.issues["K-1"].state == "implementing"
    assert state.issues["K-1"].worker_active is True

    # Complete implementing
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="K-1", result={"outcome": "done", "summary": "Built it"}), gen)
    assert state.issues["K-1"].state == "review"
    assert state.issues["K-1"].worker_active is True
    assert len(state.issues["K-1"].result_history) == 1

    # Approve review
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="K-1", result={"outcome": "approved", "feedback": "LGTM"}), gen)
    assert state.issues["K-1"].state == "done"
    assert state.issues["K-1"].worker_active is False
    assert len(state.issues["K-1"].result_history) == 2
```

- [ ] **Step 2: Write test — review rejection loop (bounces 3 times)**

Issue gets rejected at review, goes back to implementing, resubmits, rejected again, finally approved on third attempt. Verify result_history accumulates all attempts.

```python
def test_review_rejection_loop() -> None:
    config = parse_config(KANBAN_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="K-1", fields={"title": "Feature", "text": "Build it"}), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id="K-1", target_state="implementing"), gen)

    for i in range(3):
        # Implement
        state, _ = reduce(config, state, WorkerResultEvent(issue_id="K-1", result={"outcome": "done", "summary": f"Attempt {i+1}"}), gen)
        assert state.issues["K-1"].state == "review"

        if i < 2:
            # Reject
            state, _ = reduce(config, state, WorkerResultEvent(issue_id="K-1", result={"outcome": "rejected", "feedback": f"Fix #{i+1}"}), gen)
            assert state.issues["K-1"].state == "implementing"
        else:
            # Approve
            state, _ = reduce(config, state, WorkerResultEvent(issue_id="K-1", result={"outcome": "approved", "feedback": "Finally good"}), gen)
            assert state.issues["K-1"].state == "done"

    # 3 implementing results + 2 review rejections + 1 review approval = 6 history entries
    assert len(state.issues["K-1"].result_history) == 6
```

- [ ] **Step 3: Write test — multiple issues in parallel**

5 issues all in implementing simultaneously. All complete. Verify they don't interfere with each other.

```python
def test_parallel_issues() -> None:
    config = parse_config(KANBAN_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    for i in range(5):
        state, _ = reduce(config, state, CreateEvent(issue_id=f"K-{i}", fields={"title": f"Task {i}", "text": "..."}), gen)
        state, _ = reduce(config, state, AdvanceEvent(issue_id=f"K-{i}", target_state="implementing"), gen)

    # All should be in implementing with active workers
    for i in range(5):
        assert state.issues[f"K-{i}"].state == "implementing"
        assert state.issues[f"K-{i}"].worker_active is True

    # Complete them in reverse order
    for i in range(4, -1, -1):
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=f"K-{i}", result={"outcome": "done", "summary": "ok"}), gen)
        assert state.issues[f"K-{i}"].state == "review"

    # Approve all
    for i in range(5):
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=f"K-{i}", result={"outcome": "approved", "feedback": "ok"}), gen)
        assert state.issues[f"K-{i}"].state == "done"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/engine/test_scenario_kanban.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/engine/test_scenario_kanban.py
git commit -m "test: add kanban workflow scenarios"
```

---

### Task 2: CI/CD Pipeline with Merge Serialization

**Files:**
- Create: `tests/engine/test_scenario_pipeline.py`

Tests the `implementing → qa → apply (max_workers:1) → done` pipeline with conflict handling.

- [ ] **Step 1: Write test — 4 issues serialize through apply**

4 issues pass through qa, enter apply one at a time, each merges successfully.

```python
# tests/engine/test_scenario_pipeline.py
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    State,
    WorkerResultEvent,
)

PIPELINE_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: "Title"

initial: todo

states:
  todo: {}

  implementing:
    worker:
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
      result_format:
        outcome:
          type: enum
          values: [passed, failed]
          description: "QA result"
          values_description:
            passed: "Tests pass"
            failed: "Tests fail"
    on:
      passed: apply
      failed: implementing

  apply:
    max_workers: 1
    worker:
      result_format:
        outcome:
          type: enum
          values: [merged, conflict]
          description: "Merge result"
          values_description:
            merged: "Merged"
            conflict: "Conflict"
    on:
      merged: done
      conflict: implementing

  done:
    terminal: true
"""


def _counter() -> Callable[[], str]:
    n = 0
    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"
    return gen


def _advance_to_apply(config: object, state: State, issue_id: str, gen: Callable[[], str]) -> tuple[State, list[object]]:
    """Helper: advance issue through implementing and qa to apply."""
    state, _ = reduce(config, state, AdvanceEvent(issue_id=issue_id, target_state="implementing"), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=issue_id, result={"outcome": "done"}), gen)
    state, effects = reduce(config, state, WorkerResultEvent(issue_id=issue_id, result={"outcome": "passed"}), gen)
    return state, effects


def test_serialized_merge_4_issues() -> None:
    config = parse_config(PIPELINE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    # Create 4 issues
    for i in range(4):
        state, _ = reduce(config, state, CreateEvent(issue_id=f"P-{i}", fields={"title": f"Feature {i}"}), gen)

    # All pass through implementing and qa
    for i in range(4):
        state, _ = _advance_to_apply(config, state, f"P-{i}", gen)

    # Only P-0 should be active in apply, rest queued
    assert state.issues["P-0"].worker_active is True
    assert state.issues["P-0"].state == "apply"
    for i in range(1, 4):
        assert state.issues[f"P-{i}"].state == "apply"
        assert state.issues[f"P-{i}"].worker_active is False

    # Merge them one by one
    for i in range(4):
        state, effects = reduce(config, state, WorkerResultEvent(issue_id=f"P-{i}", result={"outcome": "merged"}), gen)
        assert state.issues[f"P-{i}"].state == "done"
        if i < 3:
            # Next issue should be dispatched
            dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
            next_id = f"P-{i+1}"
            assert any(e.issue_id == next_id for e in dispatch_effects)
            assert state.issues[next_id].worker_active is True
```

- [ ] **Step 2: Write test — conflict sends issue back, queue advances**

First issue in apply conflicts, goes back to implementing. Next issue in queue gets the slot.

```python
def test_conflict_frees_slot_for_next() -> None:
    config = parse_config(PIPELINE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="P-1", fields={"title": "A"}), gen)
    state, _ = reduce(config, state, CreateEvent(issue_id="P-2", fields={"title": "B"}), gen)

    state, _ = _advance_to_apply(config, state, "P-1", gen)
    state, _ = _advance_to_apply(config, state, "P-2", gen)

    assert state.issues["P-1"].worker_active is True
    assert state.issues["P-2"].worker_active is False

    # P-1 conflicts — goes back to implementing, P-2 gets the slot
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="P-1", result={"outcome": "conflict"}), gen)
    assert state.issues["P-1"].state == "implementing"
    assert state.issues["P-2"].worker_active is True
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
    assert any(e.issue_id == "P-2" for e in dispatch_effects)
```

- [ ] **Step 3: Write test — issue re-enters apply queue after conflict and full cycle**

Issue conflicts, goes through implementing → qa again, re-enters apply at the back of the queue.

```python
def test_conflict_reenter_at_back_of_queue() -> None:
    config = parse_config(PIPELINE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="P-1", fields={"title": "A"}), gen)
    state, _ = reduce(config, state, CreateEvent(issue_id="P-2", fields={"title": "B"}), gen)
    state, _ = reduce(config, state, CreateEvent(issue_id="P-3", fields={"title": "C"}), gen)

    for pid in ["P-1", "P-2", "P-3"]:
        state, _ = _advance_to_apply(config, state, pid, gen)

    # P-1 active, P-2 and P-3 queued
    assert state.issues["P-1"].worker_active is True

    # P-1 conflicts
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="P-1", result={"outcome": "conflict"}), gen)
    assert state.issues["P-1"].state == "implementing"
    assert state.issues["P-2"].worker_active is True

    # P-1 goes back through implementing → qa → apply
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="P-1", result={"outcome": "done"}), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="P-1", result={"outcome": "passed"}), gen)
    assert state.issues["P-1"].state == "apply"
    assert state.issues["P-1"].worker_active is False  # P-2 still has the slot

    # P-2 merges — P-3 should get slot (not P-1, which is behind P-3 in queue)
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="P-2", result={"outcome": "merged"}), gen)
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
    assert any(e.issue_id == "P-3" for e in dispatch_effects)
    assert state.issues["P-3"].worker_active is True
    assert state.issues["P-1"].worker_active is False
```

- [ ] **Step 4: Write test — WorkerFailed retains slot, queue doesn't advance**

```python
def test_worker_failed_retains_slot() -> None:
    config = parse_config(PIPELINE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="P-1", fields={"title": "A"}), gen)
    state, _ = reduce(config, state, CreateEvent(issue_id="P-2", fields={"title": "B"}), gen)

    state, _ = _advance_to_apply(config, state, "P-1", gen)
    state, _ = _advance_to_apply(config, state, "P-2", gen)

    from orca.engine.types import WorkerFailedEvent

    # P-1 fails — slot retained
    state, effects = reduce(config, state, WorkerFailedEvent(issue_id="P-1", error="crash"), gen)
    assert state.issues["P-1"].worker_active is True
    assert state.issues["P-2"].worker_active is False
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
    assert len(dispatch_effects) == 1
    assert dispatch_effects[0].issue_id == "P-1"  # retry, not P-2
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/engine/test_scenario_pipeline.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add tests/engine/test_scenario_pipeline.py
git commit -m "test: add CI/CD pipeline merge serialization scenarios"
```

---

### Task 3: Decomposition and Unblock Patterns

**Files:**
- Create: `tests/engine/test_scenario_decompose.py`

Tests decomposition at various depths, cascading unblock, and edge cases.

- [ ] **Step 1: Write test — single-level decompose and unblock**

Issue decomposes into 2 children. Both complete. Parent unblocks, worker re-runs, parent proceeds.

```python
# tests/engine/test_scenario_decompose.py
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
    WorkerResultEvent,
)

DECOMPOSE_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: "Title"
    text:
      type: string
      description: "Text"

initial: todo

states:
  todo: {}

  scoping:
    worker:
      result_format:
        outcome:
          type: enum
          values: [ready, decompose]
          description: "Scope result"
          values_description:
            ready: "Ready"
            decompose: "Split"
        sub_issues:
          type: list
          required_when: decompose
          items: $issue
          description: "Sub-issues"
    on:
      ready: implementing
      decompose:
        action: decompose

  implementing:
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


def _counter() -> Callable[[], str]:
    n = 0
    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"
    return gen


def _create_and_scope(config: object, state: State, issue_id: str, gen: Callable[[], str]) -> State:
    state, _ = reduce(config, state, CreateEvent(issue_id=issue_id, fields={"title": "Root", "text": "Big task"}), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id=issue_id, target_state="scoping"), gen)
    return state


def test_single_level_decompose_and_unblock() -> None:
    config = parse_config(DECOMPOSE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})
    state = _create_and_scope(config, state, "ROOT", gen)

    # Decompose into 2 children
    result = {
        "outcome": "decompose",
        "sub_issues": [
            {"title": "Child A", "text": "First part"},
            {"title": "Child B", "text": "Second part"},
        ],
    }
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result=result), gen)

    root = state.issues["ROOT"]
    assert root.blocked is True
    assert len(root.children) == 2
    child_a_id, child_b_id = root.children

    # Children are in todo (initial, passive)
    assert state.issues[child_a_id].state == "todo"
    assert state.issues[child_a_id].parent == "ROOT"

    # Process child A: todo → scoping → ready → implementing → done
    state, _ = reduce(config, state, AdvanceEvent(issue_id=child_a_id, target_state="scoping"), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_a_id, result={"outcome": "ready"}), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_a_id, result={"outcome": "done"}), gen)
    assert state.issues[child_a_id].state == "done"
    assert state.issues["ROOT"].blocked is True  # child B still not done

    # Process child B
    state, _ = reduce(config, state, AdvanceEvent(issue_id=child_b_id, target_state="scoping"), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_b_id, result={"outcome": "ready"}), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_b_id, result={"outcome": "done"}), gen)

    # Parent should be unblocked and re-dispatched
    assert state.issues["ROOT"].blocked is False
    assert state.issues["ROOT"].worker_active is True
    assert state.issues["ROOT"].state == "scoping"  # still in scoping, re-running

    # Scoping re-run: now returns ready
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result={"outcome": "ready"}), gen)
    assert state.issues["ROOT"].state == "implementing"
```

- [ ] **Step 2: Write test — 3-level deep cascading unblock**

A → decomposes into B → decomposes into C. C finishes → B unblocks → B finishes → A unblocks.

```python
def test_three_level_cascading_unblock() -> None:
    config = parse_config(DECOMPOSE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})
    state = _create_and_scope(config, state, "L1", gen)

    # L1 decomposes
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="L1", result={
        "outcome": "decompose",
        "sub_issues": [{"title": "L2", "text": "Mid"}],
    }), gen)
    l2_id = state.issues["L1"].children[0]

    # L2 enters scoping and decomposes
    state, _ = reduce(config, state, AdvanceEvent(issue_id=l2_id, target_state="scoping"), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=l2_id, result={
        "outcome": "decompose",
        "sub_issues": [{"title": "L3", "text": "Leaf"}],
    }), gen)
    l3_id = state.issues[l2_id].children[0]

    assert state.issues["L1"].blocked is True
    assert state.issues[l2_id].blocked is True

    # L3 completes
    state, _ = reduce(config, state, AdvanceEvent(issue_id=l3_id, target_state="scoping"), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=l3_id, result={"outcome": "ready"}), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=l3_id, result={"outcome": "done"}), gen)

    # L2 should be unblocked, re-running scoping
    assert state.issues[l2_id].blocked is False
    assert state.issues[l2_id].worker_active is True
    assert state.issues["L1"].blocked is True  # L2 not terminal yet

    # L2 scoping re-run returns ready, then implementing completes
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=l2_id, result={"outcome": "ready"}), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=l2_id, result={"outcome": "done"}), gen)

    # Now L1 should be unblocked
    assert state.issues["L1"].blocked is False
    assert state.issues["L1"].worker_active is True
```

- [ ] **Step 3: Write test — empty sub_issues list (edge case)**

Worker returns decompose with empty list. Parent gets blocked with 0 children. All children terminal is vacuously true → instant unblock.

```python
def test_empty_decompose() -> None:
    config = parse_config(DECOMPOSE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})
    state = _create_and_scope(config, state, "ROOT", gen)

    result = {"outcome": "decompose", "sub_issues": []}
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result=result), gen)

    # With 0 children, "all children terminal" is vacuously true
    # Parent should be unblocked immediately and re-dispatched
    assert state.issues["ROOT"].children == []
    assert state.issues["ROOT"].blocked is False
    assert state.issues["ROOT"].worker_active is True
```

- [ ] **Step 4: Write test — massive fan-out (20 children)**

```python
def test_massive_fan_out() -> None:
    config = parse_config(DECOMPOSE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})
    state = _create_and_scope(config, state, "ROOT", gen)

    sub_issues = [{"title": f"Sub {i}", "text": f"Part {i}"} for i in range(20)]
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result={
        "outcome": "decompose",
        "sub_issues": sub_issues,
    }), gen)

    assert len(state.issues["ROOT"].children) == 20
    assert state.issues["ROOT"].blocked is True

    # Complete all children
    for child_id in state.issues["ROOT"].children:
        state, _ = reduce(config, state, AdvanceEvent(issue_id=child_id, target_state="scoping"), gen)
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "ready"}), gen)
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "done"}), gen)

    assert state.issues["ROOT"].blocked is False
    assert state.issues["ROOT"].worker_active is True
```

- [ ] **Step 5: Write test — blocked issue rejects WorkerResult**

```python
def test_blocked_issue_rejects_worker_result() -> None:
    config = parse_config(DECOMPOSE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})
    state = _create_and_scope(config, state, "ROOT", gen)

    state, _ = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result={
        "outcome": "decompose",
        "sub_issues": [{"title": "Child", "text": "..."}],
    }), gen)

    # Try to send WorkerResult to blocked parent
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result={"outcome": "ready"}), gen)
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
    assert "blocked" in error_effects[0].message
```

- [ ] **Step 6: Write test — blocked issue rejects Advance**

```python
def test_blocked_issue_rejects_advance() -> None:
    config = parse_config(DECOMPOSE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="ROOT", fields={"title": "Root", "text": "..."}), gen)
    state.issues["ROOT"].blocked = True

    state, effects = reduce(config, state, AdvanceEvent(issue_id="ROOT", target_state="scoping"), gen)
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
    assert "blocked" in error_effects[0].message
```

- [ ] **Step 7: Write test — dispatch context includes resolved children**

After unblock, the DispatchWorker effect should include children with their result histories.

```python
def test_dispatch_includes_children_context() -> None:
    config = parse_config(DECOMPOSE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})
    state = _create_and_scope(config, state, "ROOT", gen)

    state, _ = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result={
        "outcome": "decompose",
        "sub_issues": [{"title": "Child", "text": "Do it"}],
    }), gen)
    child_id = state.issues["ROOT"].children[0]

    # Complete child
    state, _ = reduce(config, state, AdvanceEvent(issue_id=child_id, target_state="scoping"), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "ready"}), gen)
    state, effects = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "done"}), gen)

    # Find the dispatch for ROOT (re-run after unblock)
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect) and e.issue_id == "ROOT"]
    assert len(dispatch_effects) == 1
    children_data = dispatch_effects[0].issue["children"]
    assert len(children_data) == 1
    assert children_data[0]["issue_id"] == child_id
    assert children_data[0]["state"] == "done"
    assert len(children_data[0]["result_history"]) == 2
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/engine/test_scenario_decompose.py -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add tests/engine/test_scenario_decompose.py
git commit -m "test: add decomposition and unblock scenarios"
```

---

### Task 4: Max Workers and Queuing Stress

**Files:**
- Create: `tests/engine/test_scenario_queuing.py`

Tests max_workers capacity limits, queue ordering, and interactions with other features.

- [ ] **Step 1: Write test — 20 issues through max_workers:1 gate**

```python
# tests/engine/test_scenario_queuing.py
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

QUEUE_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: "Title"

initial: work

states:
  work:
    max_workers: 3
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


def _counter() -> Callable[[], str]:
    n = 0
    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"
    return gen


def test_max_workers_respected() -> None:
    config = parse_config(QUEUE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    # Create 10 issues — initial state is active with max_workers: 3
    for i in range(10):
        state, _ = reduce(config, state, CreateEvent(issue_id=f"Q-{i}", fields={"title": f"Task {i}"}), gen)

    # First 3 should be active, rest queued
    active = [k for k, v in state.issues.items() if v.worker_active]
    queued = [k for k, v in state.issues.items() if not v.worker_active]
    assert len(active) == 3
    assert len(queued) == 7

    # Complete one — next in queue should activate
    first_active = active[0]
    state, effects = reduce(config, state, WorkerResultEvent(issue_id=first_active, result={"outcome": "done"}), gen)
    new_active = [k for k, v in state.issues.items() if v.worker_active and v.state == "work"]
    assert len(new_active) == 3  # still 3 active
```

- [ ] **Step 2: Write test — worker failure doesn't affect queue**

```python
def test_worker_failure_retains_slot_in_capped_state() -> None:
    config = parse_config(QUEUE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    for i in range(5):
        state, _ = reduce(config, state, CreateEvent(issue_id=f"Q-{i}", fields={"title": f"Task {i}"}), gen)

    active_before = sum(1 for v in state.issues.values() if v.worker_active)
    assert active_before == 3

    # Fail the first active worker 3 times
    active_ids = [k for k, v in state.issues.items() if v.worker_active]
    for _ in range(3):
        state, effects = reduce(config, state, WorkerFailedEvent(issue_id=active_ids[0], error="crash"), gen)
        assert state.issues[active_ids[0]].worker_active is True
        active_now = sum(1 for v in state.issues.values() if v.worker_active)
        assert active_now == 3  # unchanged
```

- [ ] **Step 3: Write test — sequential drain of entire queue**

```python
def test_sequential_drain() -> None:
    """All 10 issues complete one by one as slots free up."""
    config = parse_config(QUEUE_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    for i in range(10):
        state, _ = reduce(config, state, CreateEvent(issue_id=f"Q-{i}", fields={"title": f"Task {i}"}), gen)

    completed = 0
    while completed < 10:
        active_ids = [k for k, v in state.issues.items() if v.worker_active and v.state == "work"]
        if not active_ids:
            break
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=active_ids[0], result={"outcome": "done"}), gen)
        completed += 1

    assert completed == 10
    assert all(v.state == "done" for v in state.issues.values())
```

- [ ] **Step 4: Write test — decompose fan-out respects max_workers on initial state**

```python
FANOUT_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: "Title"
    text:
      type: string
      description: "Text"

initial: work

states:
  work:
    max_workers: 2
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
          required_when: decompose
          items: $issue
          description: "Sub-issues"
    on:
      done: done
      decompose:
        action: decompose

  done:
    terminal: true
"""


def test_decompose_fanout_respects_max_workers() -> None:
    config = parse_config(FANOUT_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="ROOT", fields={"title": "Root", "text": "Big"}), gen)
    assert state.issues["ROOT"].worker_active is True

    # Decompose into 5 children — initial state has max_workers: 2
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result={
        "outcome": "decompose",
        "sub_issues": [{"title": f"Sub {i}", "text": f"Part {i}"} for i in range(5)],
    }), gen)

    active_children = [cid for cid in state.issues["ROOT"].children if state.issues[cid].worker_active]
    queued_children = [cid for cid in state.issues["ROOT"].children if not state.issues[cid].worker_active]
    assert len(active_children) == 2
    assert len(queued_children) == 3
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/engine/test_scenario_queuing.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add tests/engine/test_scenario_queuing.py
git commit -m "test: add max_workers and queuing stress scenarios"
```

---

### Task 5: Edge Cases and Error Conditions

**Files:**
- Create: `tests/engine/test_scenario_edge_cases.py`

Tests boundary conditions, invalid inputs, and unusual but valid configurations.

- [ ] **Step 1: Write tests**

```python
# tests/engine/test_scenario_edge_cases.py
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


def _counter() -> Callable[[], str]:
    n = 0
    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"
    return gen


# --- Minimal configs ---

MINIMAL_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: "Title"

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

PASSIVE_ONLY_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: "Title"

initial: backlog

states:
  backlog: {}
  ready: {}
  done:
    terminal: true
"""


def test_minimal_single_state_machine() -> None:
    """Simplest possible: work → done."""
    config = parse_config(MINIMAL_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, effects = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Simple"}), gen)
    assert state.issues["I-1"].state == "work"
    assert state.issues["I-1"].worker_active is True

    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)
    assert state.issues["I-1"].state == "done"


def test_passive_to_passive_advance() -> None:
    """Advance from one passive state to another."""
    config = parse_config(PASSIVE_ONLY_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Task"}), gen)
    assert state.issues["I-1"].state == "backlog"

    state, effects = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="ready"), gen)
    assert state.issues["I-1"].state == "ready"
    assert len(effects) == 0  # no worker to dispatch


def test_advance_to_terminal() -> None:
    """Advance from passive directly to terminal state."""
    config = parse_config(PASSIVE_ONLY_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Task"}), gen)
    state, effects = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="done"), gen)
    assert state.issues["I-1"].state == "done"


def test_advance_to_same_state() -> None:
    """Advance from passive state to itself — valid but no-op."""
    config = parse_config(PASSIVE_ONLY_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Task"}), gen)
    state, effects = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="backlog"), gen)
    assert state.issues["I-1"].state == "backlog"
    assert len(effects) == 0


def test_self_loop_state() -> None:
    """State that transitions back to itself (iterative refinement)."""
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "Title"
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
            again: "Needs more work"
            done: "Finished"
    on:
      again: refine
      done: done
  done:
    terminal: true
"""
    config = parse_config(yaml_str)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Iterate"}), gen)

    # Loop 3 times
    for i in range(3):
        state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "again"}), gen)
        assert state.issues["I-1"].state == "refine"
        assert state.issues["I-1"].worker_active is True

    # Finish
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)
    assert state.issues["I-1"].state == "done"
    assert len(state.issues["I-1"].result_history) == 4  # 3 agains + 1 done


def test_duplicate_create_errors() -> None:
    config = parse_config(MINIMAL_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "First"}), gen)
    state, effects = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Duplicate"}), gen)
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
    assert state.issues["I-1"].fields["title"] == "First"  # unchanged


def test_worker_result_on_terminal_errors() -> None:
    config = parse_config(MINIMAL_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Task"}), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)
    assert state.issues["I-1"].state == "done"

    state, effects = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1


def test_worker_result_unknown_outcome_errors() -> None:
    config = parse_config(MINIMAL_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Task"}), gen)
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "invalid"}), gen)
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
    # State should be unchanged
    assert state.issues["I-1"].state == "work"
    assert state.issues["I-1"].worker_active is True  # not freed since validation failed before mutation


def test_double_worker_result_race_condition() -> None:
    """Two WorkerResults for same issue — second should error because worker_active is False."""
    config = parse_config(MINIMAL_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Task"}), gen)

    # First result succeeds
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)

    # Second result should error (worker_active is False after first result)
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1


def test_events_on_nonexistent_issue() -> None:
    config = parse_config(MINIMAL_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    # All event types on nonexistent issue should error
    state, effects = reduce(config, state, AdvanceEvent(issue_id="NOPE", target_state="done"), gen)
    assert any(isinstance(e, ErrorEffect) for e in effects)

    state, effects = reduce(config, state, WorkerResultEvent(issue_id="NOPE", result={"outcome": "done"}), gen)
    assert any(isinstance(e, ErrorEffect) for e in effects)

    state, effects = reduce(config, state, WorkerFailedEvent(issue_id="NOPE", error="x"), gen)
    assert any(isinstance(e, ErrorEffect) for e in effects)


def test_worker_failed_when_not_active_errors() -> None:
    config = parse_config(MINIMAL_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Task"}), gen)
    state.issues["I-1"].worker_active = False  # simulate

    state, effects = reduce(config, state, WorkerFailedEvent(issue_id="I-1", error="crash"), gen)
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/engine/test_scenario_edge_cases.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add tests/engine/test_scenario_edge_cases.py
git commit -m "test: add edge case and error condition scenarios"
```

---

### Task 6: Serialization Round-Trips

**Files:**
- Create: `tests/engine/test_scenario_serialization.py`

Tests that state survives JSON serialization at various points in a workflow — simulating system restarts.

- [ ] **Step 1: Write tests**

```python
# tests/engine/test_scenario_serialization.py
import json
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    State,
    WorkerResultEvent,
)

KANBAN_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: "Title"
    text:
      type: string
      description: "Description"

initial: todo

states:
  todo: {}

  implementing:
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


def _counter(start: int = 0) -> Callable[[], str]:
    n = start
    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"
    return gen


def _roundtrip(state: State) -> State:
    """Serialize to JSON and back."""
    return State.from_dict(json.loads(json.dumps(state.to_dict())))


def test_empty_state_roundtrip() -> None:
    state = State(issues={}, worker_queues={})
    restored = _roundtrip(state)
    assert restored.issues == {}
    assert restored.worker_queues == {}


def test_mid_workflow_roundtrip() -> None:
    """State survives serialization mid-workflow."""
    config = parse_config(KANBAN_CONFIG)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Task", "text": "Do it"}), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="implementing"), gen)

    # Serialize and restore (simulating system restart)
    state = _roundtrip(state)

    # Continue processing on restored state
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)
    assert state.issues["I-1"].state == "done"
    assert len(state.issues["I-1"].result_history) == 1


def test_blocked_state_roundtrip() -> None:
    """Blocked parent with children survives serialization."""
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "Title"
    text:
      type: string
      description: "Text"

initial: todo

states:
  todo: {}

  scoping:
    worker:
      result_format:
        outcome:
          type: enum
          values: [ready, decompose]
          description: "Result"
          values_description:
            ready: "Ready"
            decompose: "Split"
        sub_issues:
          type: list
          required_when: decompose
          items: $issue
          description: "Sub-issues"
    on:
      ready: done
      decompose:
        action: decompose

  done:
    terminal: true
"""
    config = parse_config(yaml_str)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="P-1", fields={"title": "Parent", "text": "Big"}), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id="P-1", target_state="scoping"), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="P-1", result={
        "outcome": "decompose",
        "sub_issues": [{"title": "Child", "text": "Small"}],
    }), gen)

    # Serialize with blocked parent and child
    state = _roundtrip(state)

    child_id = state.issues["P-1"].children[0]
    assert state.issues["P-1"].blocked is True
    assert state.issues[child_id].parent == "P-1"
    assert state.issues[child_id].state == "todo"


def test_queue_order_survives_roundtrip() -> None:
    """Worker queue FIFO order preserved across serialization."""
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "Title"

initial: gate

states:
  gate:
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
    config = parse_config(yaml_str)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    # Create 5 issues — 1 active, 4 queued
    for i in range(5):
        state, _ = reduce(config, state, CreateEvent(issue_id=f"Q-{i}", fields={"title": f"Task {i}"}), gen)

    assert state.issues["Q-0"].worker_active is True
    queue_before = list(state.worker_queues.get("gate", []))

    # Roundtrip
    state = _roundtrip(state)

    queue_after = list(state.worker_queues.get("gate", []))
    assert queue_before == queue_after

    # Complete Q-0 on restored state — next in queue should activate
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="Q-0", result={"outcome": "done"}), gen)
    assert state.issues["Q-0"].state == "done"
    assert state.issues[queue_before[0]].worker_active is True


def test_deep_result_history_roundtrip() -> None:
    """Issue with 10 result_history entries survives roundtrip."""
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "Title"
initial: loop
states:
  loop:
    worker:
      result_format:
        outcome:
          type: enum
          values: [again, done]
          description: "Result"
          values_description:
            again: "Repeat"
            done: "Complete"
    on:
      again: loop
      done: done
  done:
    terminal: true
"""
    config = parse_config(yaml_str)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "Loop"}), gen)
    for _ in range(10):
        state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "again"}), gen)

    state = _roundtrip(state)

    assert len(state.issues["I-1"].result_history) == 10
    assert all(e.result["outcome"] == "again" for e in state.issues["I-1"].result_history)

    # Can still finish after roundtrip
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)
    assert state.issues["I-1"].state == "done"
    assert len(state.issues["I-1"].result_history) == 11
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/engine/test_scenario_serialization.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add tests/engine/test_scenario_serialization.py
git commit -m "test: add state serialization round-trip scenarios"
```

---

### Task 7: Full Suite Verification

**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 2: Run ruff and mypy**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: all PASS

- [ ] **Step 3: Commit any fixes if needed**
