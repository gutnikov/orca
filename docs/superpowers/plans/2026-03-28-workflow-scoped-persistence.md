# Workflow-Scoped Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope run state persistence per-workflow so multiple workflows on the same branch don't collide.

**Architecture:** Change run directory from `.orca/runs/{branch}/` to `.orca/runs/{branch}/{workflow}/`. The workflow name comes from the `-w` CLI flag (defaulting to `"default"`). `Persistence` and `BranchMap` accept a new `workflow` parameter; `runner.py` builds `run_dir` once and threads it through.

**Tech Stack:** Python 3.12, pytest

---

### Task 1: Add `workflow` parameter to `Persistence`

**Files:**
- Modify: `src/orca/orchestrator/persistence.py:10-11`
- Test: `tests/orchestrator/test_persistence.py`

- [ ] **Step 1: Update test for new path structure**

In `tests/orchestrator/test_persistence.py`, update `test_state_path_uses_branch_name`:

```python
def test_state_path_uses_branch_name(self, tmp_path: Path) -> None:
    """Assert path is {root}/.orca/runs/{branch}/{workflow}/state.json."""
    persistence = Persistence(tmp_path, "feature/test", "prd")

    expected_path = tmp_path / ".orca" / "runs" / "feature/test" / "prd" / "state.json"
    assert persistence.state_path == expected_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_persistence.py::TestPersistence::test_state_path_uses_branch_name -v`
Expected: FAIL — `TypeError: Persistence.__init__() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: Update `Persistence.__init__` to accept `workflow`**

In `src/orca/orchestrator/persistence.py`, change the constructor:

```python
class Persistence:
    def __init__(self, repo_root: Path, branch_name: str, workflow: str = "default") -> None:
        self.state_path = repo_root / ".orca" / "runs" / branch_name / workflow / "state.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_persistence.py::TestPersistence::test_state_path_uses_branch_name -v`
Expected: PASS

- [ ] **Step 5: Run all persistence tests to verify no regressions**

Run: `uv run pytest tests/orchestrator/test_persistence.py -v`
Expected: All 5 tests PASS (existing tests use 2-arg form, which defaults `workflow="default"`)

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/persistence.py tests/orchestrator/test_persistence.py
git commit -m "feat: add workflow parameter to Persistence for per-workflow state isolation"
```

---

### Task 2: Add `workflow` parameter to `BranchMap`

**Files:**
- Modify: `src/orca/orchestrator/branches.py:8-9`
- Test: `tests/orchestrator/test_branches.py`

- [ ] **Step 1: Update test for new path structure**

In `tests/orchestrator/test_branches.py`, update `test_file_path`:

```python
def test_file_path(self, tmp_path: Path) -> None:
    branch_map = BranchMap(tmp_path, "my-branch", "prd")
    expected_path = tmp_path / ".orca" / "runs" / "my-branch" / "prd" / "branches.json"
    assert branch_map.path == expected_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_branches.py::TestBranchMap::test_file_path -v`
Expected: FAIL — `TypeError: BranchMap.__init__() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: Update `BranchMap.__init__` to accept `workflow`**

In `src/orca/orchestrator/branches.py`, change the constructor:

```python
class BranchMap:
    def __init__(self, repo_root: Path, branch_name: str, workflow: str = "default") -> None:
        self.path = repo_root / ".orca" / "runs" / branch_name / workflow / "branches.json"
        self._map: dict[str, str] = {}
```

- [ ] **Step 4: Run all branch map tests**

Run: `uv run pytest tests/orchestrator/test_branches.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/branches.py tests/orchestrator/test_branches.py
git commit -m "feat: add workflow parameter to BranchMap for per-workflow isolation"
```

---

### Task 3: Thread `workflow` through `runner.py`

**Files:**
- Modify: `src/orca/orchestrator/runner.py:291-300, 307-421, 479-548`

- [ ] **Step 1: Add `workflow` parameter to `run()` and build `run_dir` from it**

In `src/orca/orchestrator/runner.py`, update the `run()` signature and body. Add `workflow: str = "default"` parameter. Replace all inline `run_dir` construction with a single `run_dir` variable built early:

```python
async def run(
    task_file: Path,
    branch_name: str,
    config_path: Path,
    base_ref: str | None = None,
    insights_enabled: bool = False,
    hot_sessions: set[str] | None = None,
    session_log_paths: dict[str, str] | None = None,
    insights_state: dict[str, str] | None = None,
    workflow: str = "default",
) -> None:
    """Main entry point: read task file, set up state, run orchestrator."""
    repo_root = Path.cwd()

    # Read task file
    fields = parse_task_file(task_file)

    # Load config
    config = parse_config(config_path.read_text())
    raw_config: dict[str, Any] = yaml.safe_load(config_path.read_text())
    integrations = parse_integrations(raw_config.get("integrations"))

    # Set up run directory and persistence
    run_dir = repo_root / ".orca" / "runs" / branch_name / workflow
    persistence = Persistence(repo_root, branch_name, workflow)
    branches = BranchMap(repo_root, branch_name, workflow)
    worktree_mgr = WorktreeManager(repo_root, branch_name)

    log_path = run_dir / "orca.log.jsonl"
    setup_logging(log_path)
```

- [ ] **Step 2: Update the resume block to use `run_dir`**

Replace the inline `run_dir = repo_root / ".orca" / "runs" / branch_name` on line 338 with the already-defined `run_dir`:

In the `if persistence.exists():` block, remove line 338 (`run_dir = repo_root / ...`) — `run_dir` is already defined above. The `manifest = SessionManifest(run_dir)` and `_recover_effects(..., run_dir, ...)` calls stay unchanged.

- [ ] **Step 3: Remove duplicate `run_dir` on line 421**

Remove the second `run_dir = repo_root / ".orca" / "runs" / branch_name` (line 421). `session_sync = SessionSync(run_dir=run_dir)` uses the already-defined `run_dir`.

- [ ] **Step 4: Update `main()` to pass `workflow` to `run()` and TUI**

In `main()`, derive workflow name and pass it through:

```python
    workflow = args.workflow or "default"

    if args.headless:
        asyncio.run(run(args.task_file, branch_name, config_path, base_ref=base_ref, insights_enabled=args.insights, workflow=workflow))
    else:
```

In the TUI branch, update `run_orchestrator` closure:

```python
        def run_orchestrator() -> None:
            nonlocal run_error
            try:
                asyncio.run(
                    run(
                        args.task_file,
                        branch_name,
                        config_path,
                        base_ref=base_ref,
                        insights_enabled=args.insights,
                        hot_sessions=hot_sessions,
                        session_log_paths=session_log_paths,
                        insights_state=insights_state,
                        workflow=workflow,
                    )
                )
            except BaseException as e:
                run_error = e
```

And update the TUI `run_dir`:

```python
        run_dir = repo_root / ".orca" / "runs" / branch_name / workflow
```

- [ ] **Step 5: Run lints and type check**

Run: `uv run ruff check src/orca/orchestrator/runner.py && uv run mypy src/orca/orchestrator/runner.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "feat: thread workflow name through runner for per-workflow run directories"
```

---

### Task 4: Update concurrent runs test

**Files:**
- Modify: `tests/orchestrator/test_concurrent_runs.py:58-61`

- [ ] **Step 1: Update path assertions in test**

The test on lines 58-61 asserts path isolation between branches. The paths don't need workflow since they test branch-level isolation, but the comments should note the additional workflow level. Update:

```python
        # State directories would be isolated (each workflow adds another level)
        state_a = git_repo / ".orca" / "runs" / "feature-auth"
        state_b = git_repo / ".orca" / "runs" / "feature-billing"
        assert state_a != state_b
```

No code change needed — this test asserts branch-level path components differ, which is still true. The test doesn't construct `Persistence` or `BranchMap`.

- [ ] **Step 2: Run the concurrent tests**

Run: `uv run pytest tests/orchestrator/test_concurrent_runs.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Update `session_sync.py` docstring**

In `src/orca/orchestrator/session_sync.py`, update the class docstring:

```python
class SessionManifest:
    """Read/write .orca/runs/{branch}/{workflow}/sessions.json."""
```

- [ ] **Step 4: Commit**

```bash
git add src/orca/orchestrator/session_sync.py
git commit -m "docs: update SessionManifest docstring for workflow-scoped paths"
```

---

### Task 5: Run full test suite and type check

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 2: Run lints**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: No errors

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/`
Expected: No errors
