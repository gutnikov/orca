# Worker Protocol & Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the orchestrator layer that consumes `DispatchWorkerEffect`s from the engine, spawns Claude Code CLI workers, and feeds results back to the reducer.

**Architecture:** Layered modules in `src/orca/orchestrator/` — persistence, template rendering, worktree management, worker protocol, orchestrator event loop, and CLI runner. The engine (`src/orca/engine/`) is modified only for config changes (`WorkerDef` gains `kind`, `prompt`, `timeout`). The reducer and effects are untouched.

**Tech Stack:** Python 3.12, asyncio, Jinja2, PyYAML (existing), git CLI for worktrees

**Spec:** `docs/superpowers/specs/2026-03-22-worker-protocol-design.md`

---

### Task 1: Add Jinja2 dependency

**Files:**
- Modify: `pyproject.toml:6-8`

- [ ] **Step 1: Add jinja2 to dependencies**

In `pyproject.toml`, add `jinja2` to the `dependencies` list:

```toml
dependencies = [
    "jinja2>=3.1.6",
    "pyyaml>=6.0.3",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync`
Expected: Installs jinja2

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add jinja2 dependency for prompt templating"
```

---

### Task 2: Extend WorkerDef with kind, prompt, timeout

**Files:**
- Modify: `src/orca/engine/types.py:38-40`
- Modify: `src/orca/engine/config.py:76-94`
- Test: `tests/engine/test_config.py`

- [ ] **Step 1: Write failing tests for new WorkerDef fields**

Add a `TestWorkerDefFields` class to `tests/engine/test_config.py` with these test methods:

- `test_parse_worker_with_kind_and_prompt` — parse YAML with `kind: claude-code` and `prompt: prompts/work.md`, assert both fields are set and `timeout` is None
- `test_parse_worker_with_timeout` — parse YAML with `timeout: 300`, assert it's parsed
- `test_invalid_kind_rejected` — `kind: unknown-worker` raises `ConfigValidationError` matching `"kind must be 'claude-code'"`
- `test_missing_prompt_rejected` — worker without `prompt` raises `ConfigValidationError` matching `"prompt"`
- `test_invalid_timeout_rejected` — `timeout: -1` raises `ConfigValidationError` matching `"timeout"`

Each test YAML should be a complete valid config (issue fields, initial, states with terminal) except for the specific invalid field being tested.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_config.py::TestWorkerDefFields -v`
Expected: FAIL — `WorkerDef` doesn't accept `kind`/`prompt`/`timeout` yet

- [ ] **Step 3: Update WorkerDef dataclass**

In `src/orca/engine/types.py`, replace the `WorkerDef` class (lines 38-40) to add `kind: str`, `prompt: str` as required fields before `result_format`, and `timeout: int | None = None` after it.

- [ ] **Step 4: Update config parser to read new fields**

In `src/orca/engine/config.py`, update `_parse_state` (lines 87-94). In the `if worker_data is not None:` block, read `kind`, `prompt`, and `timeout` from `worker_data` and pass them to the `WorkerDef` constructor.

- [ ] **Step 5: Add validation for new fields in `_validate`**

In `src/orca/engine/config.py`, inside `_validate`, add checks when `state.worker is not None`:
- `kind` must be `"claude-code"`
- `prompt` must be non-empty string
- `timeout`, if present, must be a positive integer

- [ ] **Step 6: Update existing test fixtures to include kind and prompt**

All existing YAML fixtures in `tests/engine/conftest.py` have `worker:` blocks without `kind`/`prompt`. Update every `worker:` block in the three fixtures (`simple_config_yaml`, `decompose_config_yaml`, `max_workers_config_yaml`) to add `kind: claude-code` and `prompt: prompts/default.md` before `result_format:`.

Also update any inline YAML strings in other test files (`test_config.py`, `test_reducer_*.py`, `test_dispatch.py`, `test_scenario_*.py`) that define worker blocks — search for `worker:` followed by `result_format:` without `kind:`.

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 8: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 9: Commit**

```bash
git add src/orca/engine/types.py src/orca/engine/config.py tests/
git commit -m "feat: add kind, prompt, timeout to WorkerDef and config parser"
```

---

### Task 3: Persistence module

**Files:**
- Create: `src/orca/orchestrator/__init__.py`
- Create: `src/orca/orchestrator/persistence.py`
- Create: `tests/orchestrator/__init__.py`
- Create: `tests/orchestrator/test_persistence.py`

- [ ] **Step 1: Create orchestrator package with empty init**

Create `src/orca/orchestrator/__init__.py` with a docstring.
Create `tests/orchestrator/__init__.py` as empty file.

- [ ] **Step 2: Write failing tests for Persistence**

Create `tests/orchestrator/test_persistence.py` with class `TestPersistence`:

- `test_save_and_load` — create empty `State`, save it, load it back, assert `to_dict()` matches
- `test_load_returns_none_when_missing` — load from nonexistent path returns `None`
- `test_exists` — false before save, true after
- `test_state_path_uses_branch_name` — assert path is `{root}/.orca/runs/{branch}/state.json`
- `test_atomic_write` — no `.tmp` file left after save

All tests use `tmp_path` fixture.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_persistence.py -v`
Expected: FAIL — module doesn't exist yet

- [ ] **Step 4: Implement Persistence**

Create `src/orca/orchestrator/persistence.py` implementing the `Persistence` class per the spec (Section: Persistence). Key: atomic writes via temp file + rename.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_persistence.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/ tests/orchestrator/
git commit -m "feat: add Persistence module for state save/load"
```

---

### Task 4: Branch mapping persistence

**Files:**
- Create: `src/orca/orchestrator/branches.py`
- Create: `tests/orchestrator/test_branches.py`

- [ ] **Step 1: Write failing tests for BranchMap**

Create `tests/orchestrator/test_branches.py` with class `TestBranchMap`:

- `test_set_and_get` — set issue-1 to "my-feature", get returns it
- `test_get_missing_returns_none` — unknown ID returns None
- `test_persistence_round_trip` — set two entries, save, create new BranchMap, load, verify both
- `test_load_returns_empty_when_no_file` — load with no file, get returns None
- `test_file_path` — assert path is `{root}/.orca/runs/{branch}/branches.json`

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_branches.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement BranchMap**

Create `src/orca/orchestrator/branches.py` per spec (Section: Issue-to-Branch Mapping). Simple dict wrapper with `set`, `get`, `save`, `load` methods. Atomic writes like Persistence.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_branches.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/branches.py tests/orchestrator/test_branches.py
git commit -m "feat: add BranchMap for issue-to-branch name mapping"
```

---

### Task 5: Template rendering module

**Files:**
- Create: `src/orca/orchestrator/template.py`
- Create: `tests/orchestrator/test_template.py`

- [ ] **Step 1: Write failing tests**

Create `tests/orchestrator/test_template.py` with class `TestRenderPrompt`:

- `test_basic_rendering` — template with `{{ issue.fields.title }}` and `{{ result_path }}`, verify both appear in output
- `test_event_log_rendering` — template iterating `issue.event_log`, verify event type appears
- `test_result_format_rendering` — template iterating `result_format.items()`, verify field name and description
- `test_missing_template_raises` — nonexistent template raises `FileNotFoundError`
- `test_subdirectory_template` — template in `prompts/` subdirectory works

All tests create template files in `tmp_path`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_template.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement render_prompt**

Create `src/orca/orchestrator/template.py` per spec (Section: Template Rendering). Use Jinja2 `Environment` with a custom loader that reads from absolute paths. No auto-escaping. Context variables: `issue`, `result_format`, `result_path`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_template.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/template.py tests/orchestrator/test_template.py
git commit -m "feat: add Jinja2 template rendering for worker prompts"
```

---

### Task 6: Result validation

**Files:**
- Create: `src/orca/orchestrator/validation.py`
- Create: `tests/orchestrator/test_validation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/orchestrator/test_validation.py` with a `RESULT_FORMAT` constant dict (outcome enum with values `[done, split]`, summary string required_when done, sub_issues list required_when split). Class `TestValidateResult`:

- `test_valid_done_result` — `{"outcome": "done", "summary": "ok"}` returns None
- `test_valid_split_result` — with sub_issues list returns None
- `test_missing_outcome` — returns error mentioning "outcome"
- `test_invalid_outcome_value` — `"unknown"` returns error
- `test_missing_required_field` — outcome "done" without summary returns error
- `test_empty_required_field` — empty summary returns error
- `test_empty_sub_issues_for_split` — empty list returns error
- `test_extra_fields_ignored` — extra fields still valid
- `test_not_a_dict` — string input returns error
- `test_required_when_not_matching` — summary not required when outcome is "split"

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_validation.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement validate_result**

Create `src/orca/orchestrator/validation.py` per spec (Section: Result Validation). Returns `str | None` — error message or None if valid.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_validation.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/validation.py tests/orchestrator/test_validation.py
git commit -m "feat: add result validation for worker output"
```

---

### Task 7: Worktree management

**Files:**
- Create: `src/orca/orchestrator/worktree.py`
- Create: `tests/orchestrator/test_worktree.py`
- Modify: `pyproject.toml` (add pytest-asyncio)

- [ ] **Step 1: Add pytest-asyncio dependency**

Add `"pytest-asyncio>=0.25.0"` to dev dependencies in `pyproject.toml`.
Run: `uv sync`

- [ ] **Step 2: Write failing tests**

Create `tests/orchestrator/test_worktree.py`. Include a `git_repo` fixture that creates a minimal git repo in `tmp_path` with one commit. Class `TestWorktreeManager`:

- `test_create_worktree` — create worktree, assert path exists and contains files
- `test_create_child_worktree` — create root worktree, then child branched from it
- `test_resolve` — returns expected path without creating anything

Tests use `@pytest.mark.asyncio()`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_worktree.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement WorktreeManager**

Create `src/orca/orchestrator/worktree.py` per spec (Section: Worktree Management). The `create` method runs `git worktree add -b {branch_name} {path} {parent_branch}` via `asyncio.create_subprocess_exec`. The `resolve` method just computes the path.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worktree.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/worktree.py tests/orchestrator/test_worktree.py pyproject.toml uv.lock
git commit -m "feat: add WorktreeManager for git worktree lifecycle"
```

---

### Task 8: Worker protocol and ClaudeCodeWorker

**Files:**
- Create: `src/orca/orchestrator/worker.py`
- Create: `tests/orchestrator/test_worker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/orchestrator/test_worker.py`. Tests mock the subprocess (never spawn real `claude`). Class `TestClaudeCodeWorker`:

- `test_successful_execution` — mock subprocess returns 0, result file written with valid JSON, assert `WorkerSuccess`
- `test_nonzero_exit_code` — mock returns exit code 1, assert `WorkerFailure` with "exit code"
- `test_missing_result_file` — subprocess succeeds but no result file, assert `WorkerFailure`
- `test_invalid_result_validation` — result file missing required field, assert `WorkerFailure`
- `test_previous_result_file_deleted` — pre-existing result file is cleaned up before run
- `test_session_log_created` — session log file created in `.orca/sessions/`

Use `unittest.mock.patch` to mock `asyncio.create_subprocess_exec` and `render_prompt`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_worker.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement worker module**

Create `src/orca/orchestrator/worker.py` per spec (Section: Worker Protocol). Contains:

- `WorkerSuccess` and `WorkerFailure` frozen dataclasses
- `WorkerOutcome` type alias
- `Worker` Protocol class with `execute` method
- `ClaudeCodeWorker` class implementing the protocol

The `execute` method: deletes old result file, renders prompt, spawns `claude` subprocess with `stream-json` output, streams stdout to session log file, waits for exit, reads and validates result file.

The `execute` signature takes `effect`, `workdir`, `result_path`, and `prompt_path`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worker.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/worker.py tests/orchestrator/test_worker.py
git commit -m "feat: add Worker protocol and ClaudeCodeWorker implementation"
```

---

### Task 9: Orchestrator event loop

**Files:**
- Create: `src/orca/orchestrator/orchestrator.py`
- Create: `tests/orchestrator/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/orchestrator/test_orchestrator.py`. Define a `MockWorker` that returns predefined `WorkerOutcome`s by state name. Class `TestOrchestrator`:

- `test_simple_run_to_completion` — two-state workflow (todo → implementing → done), mock worker returns success for both, assert root issue reaches terminal

Use a `_counter` helper for deterministic ID generation and a fixed `_now` function.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement Orchestrator**

Create `src/orca/orchestrator/orchestrator.py` per spec (Section: Orchestrator Event Loop). The `Orchestrator` class:

- Constructor takes `config`, `state`, `root_branch`, `persistence`, `branches`, `workers` dict, `generate_id`, `now`, `worktree_resolver`
- `run(root_issue_id, initial_effects)` — async event loop that processes effects, spawns workers as asyncio tasks, awaits completion with `FIRST_COMPLETED`, builds events from outcomes, calls `reduce`, persists state, loops until root issue is terminal
- Resolves `kind`/`prompt`/`timeout` from `config.states[effect.state].worker`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py tests/orchestrator/test_orchestrator.py
git commit -m "feat: add Orchestrator async event loop"
```

---

### Task 10: CLI runner

**Files:**
- Create: `src/orca/orchestrator/runner.py`
- Create: `tests/orchestrator/test_runner.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing tests**

Create `tests/orchestrator/test_runner.py`. Class `TestParseTaskFile`:

- `test_parse_title_and_description` — multiline file, line 1 = title, rest = description
- `test_title_only` — single line file
- `test_strips_whitespace` — leading/trailing whitespace stripped

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_runner.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement runner**

Create `src/orca/orchestrator/runner.py` per spec (Section: CLI Entry Point). Contains:

- `parse_task_file(path)` — returns `(title, description)` tuple
- `run(task_file, branch_name)` — async main entry: reads task, loads config, creates branch + worktree, initializes or resumes state, runs orchestrator
- `_recover_effects(config, state, ...)` — crash recovery: checks result files before re-dispatching
- `main()` — CLI entry point using argparse

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_runner.py -v`
Expected: ALL PASS

- [ ] **Step 5: Add CLI entry point to pyproject.toml**

Add `[project.scripts]` section: `orca = "orca.orchestrator.runner:main"`
Run: `uv sync`

- [ ] **Step 6: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/runner.py tests/orchestrator/test_runner.py pyproject.toml uv.lock
git commit -m "feat: add CLI runner with orca run command"
```

---

### Task 11: Integration test — full workflow

**Files:**
- Create: `tests/orchestrator/test_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/orchestrator/test_integration.py`. Define a `ScriptedWorker` that returns outcomes based on `(issue_id, state)` tuples. Define a `DECOMPOSE_CONFIG` YAML with states: planning (can decompose or implement), implementing, done.

Class `TestIntegrationDecompose`:

- `test_decompose_and_complete` — root issue decomposes into two sub-issues (db, api with dependency on db), both implement and complete, parent re-runs and completes. Assert root reaches terminal.

This test exercises: config parsing, reducer, orchestrator event loop, mock worker, persistence, branch mapping, decomposition, dependency resolution, cascading unblock.

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/orchestrator/test_integration.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrator/test_integration.py
git commit -m "test: add integration test for full orchestrator workflow"
```

---

### Task 12: Orchestrator exports and .gitignore

**Files:**
- Modify: `src/orca/orchestrator/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add public exports**

Update `src/orca/orchestrator/__init__.py` to export all public types: `BranchMap`, `ClaudeCodeWorker`, `Orchestrator`, `Persistence`, `Worker`, `WorkerFailure`, `WorkerOutcome`, `WorkerSuccess`, `WorktreeManager`, `main`, `parse_task_file`, `run`, `render_prompt`, `validate_result`.

- [ ] **Step 2: Add .orca/ to .gitignore**

Ensure `.gitignore` contains `.orca/`.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Run linter and type checker**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/__init__.py .gitignore
git commit -m "feat: add orchestrator public exports and .gitignore for .orca/"
```
