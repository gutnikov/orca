# Engine Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add event log (replacing result_history), hop limits (max_visits/max_hops), and ASCII visualization to the state machine engine.

**Architecture:** Three layered changes: (1) event log replaces result_history in types/state/reducer/dispatch, (2) hop limits add counters to state and checks to reducer, (3) formatting utility reads state and produces ASCII output. The event log is foundational — the other two depend on it.

**Tech Stack:** Python 3.12, dataclasses, pytest, datetime (for elapsed time formatting)

**Spec:** `docs/superpowers/specs/2026-03-22-engine-improvements-design.md`

---

## File Structure

```
src/orca/engine/
├── types.py        — MODIFY: replace ResultHistoryEntry with EventLogEntry, add timestamp to events, add visit_counts/hop_count to Issue, add max_hops to config, add max_visits to StateDef
├── config.py       — MODIFY: parse max_hops and max_visits, add validation rules
├── dispatch.py     — MODIFY: update build_issue_context to use event_log, widen effect types, add event log append helper
├── reducer.py      — MODIFY: add now parameter, emit log entries, add hop limit checks
├── formatting.py   — CREATE: format_issues() ASCII visualization
├── __init__.py     — MODIFY: update exports
tests/engine/
├── test_types.py              — MODIFY: update for new fields
├── test_config.py             — MODIFY: add max_hops/max_visits tests
├── test_dispatch.py           — MODIFY: update for event_log
├── test_reducer_create.py     — MODIFY: update for event_log, timestamps, visit_counts
├── test_reducer_advance.py    — MODIFY: update for event_log, timestamps, hop_count
├── test_reducer_worker_result.py — MODIFY: update for event_log, timestamps, hop limits
├── test_reducer_worker_failed.py — MODIFY: update for event_log, timestamps
├── test_scenario_*.py (6 files) — MODIFY: update for new API
├── test_event_log.py          — CREATE: dedicated event log entry tests
├── test_hop_limits.py         — CREATE: hop limit tests
├── test_formatting.py         — CREATE: ASCII visualization tests
├── conftest.py                — MODIFY: add timestamp helpers, update fixtures
```

---

### Task 1: Update Types — EventLogEntry, Timestamps, Hop Counters

**Files:**
- Modify: `src/orca/engine/types.py`
- Modify: `tests/engine/test_types.py`

This is the foundational change. Everything else builds on it.

- [ ] **Step 1: Update types.py**

Replace `ResultHistoryEntry` with `EventLogEntry`. Add `timestamp` to all events. Add `event_log`, `visit_counts`, `hop_count` to `Issue`. Add `max_hops` to `StateMachineConfig`. Add `max_visits` to `StateDef`. Update `Issue.to_dict()`/`from_dict()` with backward-compatible defaults.

Key changes:
- `ResultHistoryEntry` → `EventLogEntry(timestamp: str, type: str, data: dict[str, Any])` with `to_dict()`/`from_dict()` methods
- `Issue.result_history` → `Issue.event_log: list[EventLogEntry]`
- `Issue` gains `visit_counts: dict[str, int]` and `hop_count: int`
- `Issue.from_dict()` handles missing `visit_counts` (default `{}`), `hop_count` (default `0`), and `event_log` (default `[]`)
- All events gain `timestamp: str` field
- `StateMachineConfig` gains `max_hops: int | None = None`
- `StateDef` gains `max_visits: int | None = None`

- [ ] **Step 2: Update test_types.py**

Update all tests to use `event_log=[]` instead of `result_history=[]`. Update event construction to include `timestamp`. Add tests for:
- `EventLogEntry` construction and round-trip
- `Issue` with `visit_counts` and `hop_count` round-trip
- `Issue.from_dict()` backward compatibility (missing new fields)
- Events with `timestamp` field
- `StateMachineConfig` with `max_hops`
- `StateDef` with `max_visits`

- [ ] **Step 3: Run tests (expect many failures from other files — types tests should pass)**

Run: `uv run pytest tests/engine/test_types.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: replace ResultHistoryEntry with EventLogEntry, add timestamps and hop counters to types"
```

---

### Task 2: Update Config Parsing — max_hops and max_visits

**Files:**
- Modify: `src/orca/engine/config.py`
- Modify: `tests/engine/test_config.py`

- [ ] **Step 1: Update config.py**

- Parse `max_hops` from top-level YAML into `StateMachineConfig`
- Parse `max_visits` from state definitions into `StateDef`
- Add validation rules: both must be positive integers if present

- [ ] **Step 2: Update test_config.py**

Add tests:
- Config with `max_hops` parsed correctly
- Config with `max_visits` on a state parsed correctly
- Validation: `max_hops: 0` → error
- Validation: `max_hops: -1` → error
- Validation: `max_visits: 0` → error

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/engine/test_config.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add max_hops and max_visits config parsing and validation"
```

---

### Task 3: Update Dispatch — event_log in context, effect type widening

**Files:**
- Modify: `src/orca/engine/dispatch.py`
- Modify: `tests/engine/test_dispatch.py`

- [ ] **Step 1: Update dispatch.py**

- `build_issue_context()`: replace `result_history` with `event_log` in both parent and child contexts
- Widen `effects` parameter type from `list[DispatchWorkerEffect]` to `list[Effect]` in `try_dispatch`, `backfill_queue`, and helper functions. This is needed for Task 5 (hop limits emit ErrorEffect from these paths).
- Add helper: `append_log(issue: Issue, timestamp: str, entry_type: str, data: dict[str, Any]) -> None` that appends an `EventLogEntry` to the issue's `event_log`. Centralizes log entry creation.

**Note:** Intermediate commits (Tasks 1-7) will break some test files that haven't been migrated yet. This is expected — the full suite passes only after Task 8. Use a feature branch; don't expect CI to pass on intermediate commits.

- [ ] **Step 2: Update test_dispatch.py**

- Update all `Issue()` construction to use `event_log=[]` instead of `result_history=[]`
- Add `visit_counts={}` and `hop_count=0` to Issue construction
- Update `test_dispatch_includes_resolved_children` to assert `event_log` in context instead of `result_history`

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/engine/test_dispatch.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: update dispatch to use event_log and widen effect types"
```

---

### Task 4: Update Reducer — Event Log Emission

**Files:**
- Modify: `src/orca/engine/reducer.py`
- Modify: `tests/engine/test_reducer_create.py`
- Modify: `tests/engine/test_reducer_advance.py`
- Modify: `tests/engine/test_reducer_worker_result.py`
- Modify: `tests/engine/test_reducer_worker_failed.py`
- Create: `tests/engine/test_event_log.py`

This is the largest task. The reducer gains `now` parameter and emits log entries at every action point.

- [ ] **Step 1: Update reducer.py**

- Add `now: Callable[[], str]` parameter to `reduce()`. Call `now()` once at the top, store as `ts`.
- Pass `ts` through to all handlers.
- **Timestamp rule:** use `event.timestamp` for log entries that directly record an incoming event (`created` from CreateEvent, `advanced` from AdvanceEvent, `worker_result` from WorkerResultEvent, `worker_failed` from WorkerFailedEvent). Use `ts` (from `now()`) for reducer-initiated entries (`worker_dispatched`, `transitioned`, `decomposition_blocked`, `dependency_blocked`, `unblocked`, sub-issue `created`).
- In `_handle_create`: append `created` log entry to issue. Initialize `visit_counts={config.initial: 1}`, `hop_count=0`. On dispatch, append `worker_dispatched` log entry.
- In `_handle_advance`: append `advanced` log entry with `{from, to}`. Increment `visit_counts[target]` and `hop_count`. On dispatch, append `worker_dispatched` log entry.
- In `_handle_worker_result`: append `worker_result` log entry. On transition, append `transitioned` log entry, increment `visit_counts` and `hop_count`. On decompose, append `decomposition_blocked` log entry to parent, `created` log entry to each child. Increment `hop_count` for decompose.
- In `_handle_worker_failed`: append `worker_failed` log entry. On retry dispatch, append `worker_dispatched` log entry.
- In `_cascading_unblock`: append `unblocked` log entry. On dispatch, append `worker_dispatched` log entry.
- In `_apply_decompose`: append `created` to each child, `dependency_blocked` to children that have depends_on.
- Update all `Issue()` construction to use `event_log=[]` instead of `result_history=[]`, add `visit_counts` and `hop_count`.
- Replace `issue.result_history.append(ResultHistoryEntry(...))` with `append_log(issue, ts, "worker_result", {...})`.
- Update all handler signatures to accept `ts: str` parameter.
- Widen `_apply_transition` and `_apply_decompose` signatures from `list[DispatchWorkerEffect]` to `list[Effect]`. This is needed for Task 5 (hop limits emit ErrorEffect from these paths).
- Update `try_dispatch` calls to also append `worker_dispatched` log entries. Since `try_dispatch` is in dispatch.py, the reducer appends `worker_dispatched` after each `try_dispatch` call by checking if effects list grew (compare length before/after call).
- **WorkerFailed log ordering:** In `_handle_worker_failed`, append `worker_failed` log entry FIRST, then `worker_dispatched` log entry, then build the retry `DispatchWorkerEffect` via `build_issue_context`. This ensures the retrying worker sees both the failure and the re-dispatch in its context.

- [ ] **Step 2: Update test_reducer_create.py**

- Add `timestamp` to all event constructors
- Add `now` parameter to all `reduce()` calls (use `lambda: "2026-01-01T00:00:00Z"` or a counter-based clock)
- Update assertions: `result_history` → `event_log`
- Add assertions for `created` and `worker_dispatched` log entries
- Add assertions for `visit_counts` initialization

- [ ] **Step 3: Update test_reducer_advance.py**

- Same timestamp/now updates
- Add assertions for `advanced` log entries
- Add assertions for `hop_count` and `visit_counts` changes

- [ ] **Step 4: Update test_reducer_worker_result.py**

- Same timestamp/now updates
- Update all `result_history` assertions to `event_log`
- Add assertions for `worker_result`, `transitioned`, `decomposition_blocked`, `created` (sub-issues) log entries
- Add assertions for `hop_count` increments on transitions and decompose

- [ ] **Step 5: Update test_reducer_worker_failed.py**

- Same timestamp/now updates
- Add assertions for `worker_failed` and `worker_dispatched` log entries

- [ ] **Step 6: Create test_event_log.py — dedicated event log tests**

Tests focused on log entry correctness:
- `test_create_logs_created_entry` — verify timestamp, type, data
- `test_advance_logs_advanced_entry` — verify from/to in data
- `test_advance_does_not_log_transitioned` — Advance produces `advanced`, not `transitioned`
- `test_worker_result_logs_result_and_transition` — both entries present
- `test_worker_failed_logs_failed_and_dispatch` — both entries present
- `test_decompose_logs_blocked_and_child_created` — parent gets `decomposition_blocked`, children get `created`
- `test_unblock_logs_unblocked_entry` — after all children terminal
- `test_dependency_blocked_child_gets_log_entry` — child with depends_on gets `dependency_blocked`
- `test_event_log_timestamps_use_event_timestamp` — verify `worker_result` entry uses event.timestamp
- `test_full_lifecycle_log` — issue goes through create → advance → implement → transition → done, verify complete log sequence

- [ ] **Step 7: Run all reducer and event log tests**

Run: `uv run pytest tests/engine/test_reducer_create.py tests/engine/test_reducer_advance.py tests/engine/test_reducer_worker_result.py tests/engine/test_reducer_worker_failed.py tests/engine/test_event_log.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git commit -m "feat: add event log emission to reducer, replace result_history"
```

---

### Task 5: Add Hop Limit Checks to Reducer

**Files:**
- Modify: `src/orca/engine/reducer.py`
- Create: `tests/engine/test_hop_limits.py`

- [ ] **Step 1: Add limit checks to reducer.py**

In `_handle_worker_result`, before `_apply_transition`:
- Check `max_visits` on target state: if `issue.visit_counts.get(target, 0) + 1 > max_visits` → error
- Check `max_hops` on config: if `issue.hop_count + 1 > max_hops` → error
- On limit hit: set `worker_active=False`, backfill queue, append `limit_reached` log entry, emit `ErrorEffect`, return

In `_handle_worker_result`, before `_apply_decompose`:
- Check `max_hops`: if `issue.hop_count + 1 > max_hops` → error (same pattern)

In `_handle_advance`, before moving to target state:
- Same checks for `max_visits` and `max_hops`

- [ ] **Step 2: Create test_hop_limits.py**

Tests:
- `test_max_visits_blocks_transition` — state with max_visits:2, issue visits it 2 times, third attempt errors
- `test_max_hops_blocks_transition` — config with max_hops:3, issue does 3 hops, fourth attempt errors
- `test_max_visits_on_advance` — advance to state with max_visits, verify it's checked
- `test_decompose_increments_hop_count` — verify hop_count goes up on decompose
- `test_limit_frees_slot_and_backfills` — in max_workers state, limit hit frees slot, queued issue dispatched
- `test_limit_logs_limit_reached` — verify log entry
- `test_no_limit_by_default` — without max_visits/max_hops, loops run freely
- `test_loop_detection_implementing_qa` — realistic: implementing → qa → implementing loop with max_visits:3 on implementing, verify it stops
- `test_decompose_loop_detection` — parent decomposes, child completes instantly, parent unblocks and re-runs, decomposes again — verify max_hops stops this cycle

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/engine/test_hop_limits.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add hop limit checks (max_visits, max_hops) to reducer"
```

---

### Task 6: ASCII Visualization

**Files:**
- Create: `src/orca/engine/formatting.py`
- Create: `tests/engine/test_formatting.py`

- [ ] **Step 1: Create test_formatting.py**

Tests:
- `test_single_root_issue` — one issue, verify format: `ISSUE-1 [todo] ... 0m`
- `test_terminal_issue_no_marker` — done issue shows just time, no `...`
- `test_parent_with_children` — decomposed parent with 2 children, verify tree connectors
- `test_depends_on_annotation` — child with depends_on shows annotation
- `test_elapsed_time_formatting` — verify minutes, hours, days formatting
- `test_worker_queues_shown` — state with queued issues, verify footer
- `test_no_created_event_shows_question_mark` — issue without created log entry
- `test_sort_order_by_id` — verify lexicographic sort of roots and children
- `test_empty_state` — no issues, empty string output
- `test_deep_nesting` — 3-level decomposition tree, verify indentation

- [ ] **Step 2: Create formatting.py**

Implement `format_issues(state, config, now)`:
1. Find roots (no `decomposed_from`)
2. Sort by ID
3. For each root, recursively render children (sorted by ID)
4. Show `depends_on` annotations
5. Show `...` for non-terminal states
6. Compute elapsed time from `created` log entry
7. Show worker queues at bottom

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/engine/test_formatting.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add ASCII visualization for issue state"
```

---

### Task 7: Update Public API and Exports

**Files:**
- Modify: `src/orca/engine/__init__.py`

- [ ] **Step 1: Update __init__.py**

- Remove `ResultHistoryEntry` (if exported)
- Add `EventLogEntry`
- Add `format_issues` from `formatting.py`

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/engine/test_types.py::TestPublicAPI -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: update public API exports with EventLogEntry and format_issues"
```

---

### Task 8: Migrate Scenario Tests

**Files:**
- Modify: `tests/engine/test_scenario_kanban.py`
- Modify: `tests/engine/test_scenario_pipeline.py`
- Modify: `tests/engine/test_scenario_decompose.py`
- Modify: `tests/engine/test_scenario_queuing.py`
- Modify: `tests/engine/test_scenario_edge_cases.py`
- Modify: `tests/engine/test_scenario_serialization.py`
- Modify: `tests/engine/conftest.py`

All scenario tests need the same migration pattern:
- Add `timestamp` to all event constructors
- Add `now` (clock function) to all `reduce()` calls
- Replace `result_history=[]` with `event_log=[]` in any direct `Issue()` construction
- Add `visit_counts={}` and `hop_count=0` to any direct `Issue()` construction
- Update assertions that check `result_history` to check `event_log` (filter by type)
- Update conftest: add a `_clock()` fixture or helper

- [ ] **Step 1: Update conftest.py**

Add helper:
```python
def make_clock(start: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: start
```

Add configs with `max_hops`/`max_visits` if needed.

- [ ] **Step 2: Migrate each scenario test file**

Apply the migration pattern to all 6 files. For each:
- Find/replace `result_history=[]` → `event_log=[], visit_counts={}, hop_count=0`
- Add `timestamp="2026-01-01T00:00:00Z"` to event constructors
- Add `lambda: "2026-01-01T00:00:00Z"` as `now` to `reduce()` calls
- Update assertions checking `result_history` length to check `event_log` filtered by type

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Run ruff and mypy**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: migrate all scenario tests to event_log API"
```

---

### Task 9: Final Verification

**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS (134+ original + new tests)

- [ ] **Step 2: Run ruff, format, mypy**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 3: Update original engine spec**

Update `docs/superpowers/specs/2026-03-22-state-machine-engine-design.md` to reflect all changes: `event_log` replacing `result_history`, new reducer signature with `now`, timestamps on events, `visit_counts`/`hop_count`, `max_visits`/`max_hops`.

- [ ] **Step 4: Verify CI config includes test job**

Already done in previous PR — the `test` job runs `uv run pytest -v`.

- [ ] **Step 5: Commit**

```bash
git commit -m "docs: update original engine spec for event log and hop limits"
```
