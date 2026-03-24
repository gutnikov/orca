# CLI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the orca CLI by removing subcommands, supporting workflow file selection, and defaulting the branch to the current git branch.

**Architecture:** All changes are in `runner.py` (CLI entry point) and docs. The engine, orchestrator, TUI, and worker layers are untouched. The `run()` async function gains a `config_path` parameter; `main()` handles argument parsing, config resolution, and branch defaulting before calling `run()`.

**Tech Stack:** Python 3.12, argparse, subprocess (for `git rev-parse`)

**Spec:** `docs/superpowers/specs/2026-03-24-cli-redesign-design.md`

---

## File Map

- **Modify:** `src/orca/orchestrator/runner.py` — rewrite argparse, update `run()` signature, add helpers
- **Create:** `tests/orchestrator/test_cli.py` — tests for new CLI behavior (config resolution, branch defaulting)
- **Modify:** `CLAUDE.md` — update usage line
- **Modify:** `README.md` — update usage examples and options

---

### Task 1: Add `resolve_config_path` helper with tests

**Files:**
- Create: `tests/orchestrator/test_cli.py`
- Modify: `src/orca/orchestrator/runner.py`

- [ ] **Step 1: Write failing tests for config path resolution**

In `tests/orchestrator/test_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from orca.orchestrator.runner import resolve_config_path


class TestResolveConfigPath:
    def test_default_returns_orca_yml(self, tmp_path: Path) -> None:
        (tmp_path / "orca.yml").write_text("initial: todo")
        assert resolve_config_path(tmp_path, None) == tmp_path / "orca.yml"

    def test_workflow_shorthand(self, tmp_path: Path) -> None:
        (tmp_path / "orca.develop.yml").write_text("initial: todo")
        assert resolve_config_path(tmp_path, "develop") == tmp_path / "orca.develop.yml"

    def test_missing_default_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            resolve_config_path(tmp_path, None)

    def test_missing_workflow_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            resolve_config_path(tmp_path, "develop")

    def test_error_lists_available_files(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "orca.yml").write_text("initial: todo")
        (tmp_path / "orca.test.yml").write_text("initial: todo")
        with pytest.raises(SystemExit):
            resolve_config_path(tmp_path, "develop")
        captured = capsys.readouterr()
        assert "orca.yml" in captured.err
        assert "orca.test.yml" in captured.err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_config_path'`

- [ ] **Step 3: Implement `resolve_config_path`**

Add to `src/orca/orchestrator/runner.py`, after the `_now()` function (after line 51):

```python
def resolve_config_path(repo_root: Path, workflow: str | None) -> Path:
    """Resolve the workflow config file path.

    Args:
        repo_root: Repository root directory.
        workflow: Shorthand name (e.g. "develop" -> "orca.develop.yml"), or None for "orca.yml".

    Returns:
        Resolved config file path.

    Raises:
        SystemExit: If the resolved file does not exist.
    """
    import sys

    config_name = f"orca.{workflow}.yml" if workflow else "orca.yml"
    config_path = repo_root / config_name
    if config_path.exists():
        return config_path

    available = sorted({*repo_root.glob("orca.yml"), *repo_root.glob("orca.*.yml")})
    available_str = ", ".join(p.name for p in available) if available else "(none found)"
    print(f"Error: {config_name} not found in {repo_root}. Available: {available_str}", file=sys.stderr)
    raise SystemExit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_cli.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/orchestrator/runner.py tests/orchestrator/test_cli.py && uv run mypy src/orca/orchestrator/runner.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add tests/orchestrator/test_cli.py src/orca/orchestrator/runner.py
git commit -m "feat: add resolve_config_path helper with tests"
```

---

### Task 2: Add `resolve_branch` helper with tests

**Files:**
- Modify: `tests/orchestrator/test_cli.py`
- Modify: `src/orca/orchestrator/runner.py`

- [ ] **Step 1: Write failing tests for branch resolution**

Append to `tests/orchestrator/test_cli.py`:

```python
import subprocess
from unittest.mock import patch

from orca.orchestrator.runner import resolve_branch


class TestResolveBranch:
    def test_explicit_branch_returned_as_is(self) -> None:
        assert resolve_branch("my-feature") == "my-feature"

    def test_none_resolves_to_current_branch(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n")
            assert resolve_branch(None) == "main"

    def test_detached_head_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="HEAD\n")
            with pytest.raises(SystemExit):
                resolve_branch(None)

    def test_empty_stdout_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="\n")
            with pytest.raises(SystemExit):
                resolve_branch(None)

    def test_nonzero_returncode_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=128, stdout="")
            with pytest.raises(SystemExit):
                resolve_branch(None)

    def test_git_failure_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            with pytest.raises(SystemExit):
                resolve_branch(None)
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_cli.py::TestResolveBranch -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_branch'`

- [ ] **Step 3: Implement `resolve_branch`**

Add to `src/orca/orchestrator/runner.py`, right after `resolve_config_path`:

```python
def resolve_branch(branch: str | None) -> str:
    """Resolve the branch name, defaulting to current git branch.

    Args:
        branch: Explicit branch name, or None to auto-detect.

    Returns:
        Resolved branch name.

    Raises:
        SystemExit: If auto-detection fails (detached HEAD, not a git repo).
    """
    import subprocess
    import sys

    if branch is not None:
        return branch

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        name = result.stdout.strip()
        if result.returncode != 0 or not name or name == "HEAD":
            print("Error: cannot detect current branch (detached HEAD?). Specify with -b.", file=sys.stderr)
            raise SystemExit(1)
        return name
    except FileNotFoundError:
        print("Error: git not found. Specify branch with -b.", file=sys.stderr)
        raise SystemExit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_cli.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/orchestrator/runner.py tests/orchestrator/test_cli.py && uv run mypy src/orca/orchestrator/runner.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add tests/orchestrator/test_cli.py src/orca/orchestrator/runner.py
git commit -m "feat: add resolve_branch helper with tests"
```

---

### Task 3: Update `run()` signature and rewrite `main()` — new argparse, remove `watch`

**Files:**
- Modify: `src/orca/orchestrator/runner.py`

- [ ] **Step 1: Update `run()` to accept `config_path` parameter**

Change the function signature at line 143 from:

```python
async def run(task_file: Path, branch_name: str, insights_enabled: bool = False) -> None:
```

to:

```python
async def run(task_file: Path, branch_name: str, config_path: Path, insights_enabled: bool = False) -> None:
```

Replace lines 150-152:

```python
    # Load config
    config_path = repo_root / "orca.yml"
    config = parse_config(config_path.read_text())
```

with:

```python
    # Load config
    config = parse_config(config_path.read_text())
```

- [ ] **Step 2: Replace the entire `main()` function**

Replace `main()` (lines 276-353) with:

```python
def main() -> None:
    """CLI entry point: orca <task_file> [-b branch] [-w workflow] [--headless] [--insights]."""
    parser = argparse.ArgumentParser(prog="orca", description="Orca orchestrator CLI")
    parser.add_argument("task_file", type=Path, help="Path to the task file")
    parser.add_argument("-b", "--branch", type=str, default=None, help="Git branch name (default: current branch)")
    parser.add_argument(
        "-w", "--workflow", type=str, default=None, help="Workflow name shorthand (e.g. 'develop' -> orca.develop.yml)"
    )
    parser.add_argument("--headless", action="store_true", help="Run without TUI (headless mode)")
    parser.add_argument("--insights", action="store_true", help="Enable insights agent for progress monitoring")

    args = parser.parse_args()

    repo_root = Path.cwd()
    config_path = resolve_config_path(repo_root, args.workflow)
    branch_name = resolve_branch(args.branch)

    if args.headless:
        asyncio.run(run(args.task_file, branch_name, config_path, insights_enabled=args.insights))
    else:
        import threading

        run_error: BaseException | None = None

        def run_orchestrator() -> None:
            nonlocal run_error
            try:
                asyncio.run(run(args.task_file, branch_name, config_path, insights_enabled=args.insights))
            except BaseException as e:
                run_error = e

        thread = threading.Thread(target=run_orchestrator, daemon=True)
        thread.start()

        try:
            from orca.tui.app import OrcaApp
        except ImportError:
            print("Error: textual is not installed. Install with: uv pip install 'orca[tui]'")
            raise SystemExit(1) from None

        run_dir = repo_root / ".orca" / "runs" / branch_name
        config = parse_config(config_path.read_text())

        app = OrcaApp(run_dir=run_dir, branch_name=branch_name, config=config, insights_enabled=args.insights)
        app.run()

        # TUI closed — force exit to kill orchestrator thread and any subprocesses
        import os
        import signal

        os.kill(os.getpid(), signal.SIGTERM)
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests PASS

- [ ] **Step 4: Run linters**

Run: `uv run ruff check src/orca/orchestrator/runner.py && uv run mypy src/orca/orchestrator/runner.py`
Expected: No errors

- [ ] **Step 5: Smoke test the CLI help**

Run: `uv run orca --help`
Expected output should show:
```
usage: orca [-h] [-b BRANCH] [-w WORKFLOW] [--headless] [--insights] task_file
```

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "feat: rewrite CLI — remove subcommands, add -b/-w flags, thread config_path"
```

---

### Task 4: Update docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update CLAUDE.md**

Replace line 18:
```
- `orca run <task.md> <branch-name>` — run a workflow
```
with:
```
- `orca <task.md> [-b branch] [-w workflow] [--headless] [--insights]` — run a workflow
```

- [ ] **Step 2: Update README.md**

In the "Run it" section (line 94), replace:
```bash
orca run task.md my-feature-branch
```
with:
```bash
orca task.md -b my-feature-branch
```

Remove the "Watch a running workflow" section (lines 103-109) entirely.

In the "Options" section (lines 111-117), replace:
```bash
orca run task.md branch-name              # run with TUI
orca run task.md branch-name --headless   # run without TUI
orca run task.md branch-name --insights   # enable progress monitoring agent
```
with:
```bash
orca task.md -b branch-name              # run with TUI (branch explicit)
orca task.md                             # run with TUI (branch = current)
orca task.md --headless                  # run without TUI
orca task.md -w develop                  # use orca.develop.yml workflow
orca task.md --insights                  # enable progress monitoring agent
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update CLI usage for new syntax"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 2: Run all linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors

- [ ] **Step 3: Verify CLI works end-to-end**

Run: `uv run orca --help`
Verify output matches new interface.

Run: `uv run orca nonexistent.md` (in a git repo)
Expected: Error about file not found (argparse or file read error, not an old subcommand error).
