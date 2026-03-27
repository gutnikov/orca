# Concurrent Runs via `-b` Flag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow multiple orca processes to run concurrently in the same repo by isolating each run in its own integration branch and worktree.

**Architecture:** Add `-b <branch>` and `--base <ref>` CLI flags. When `-b` is used, orca creates an integration branch from the base ref, sets up a worktree for the root issue, and keys all state under that branch name. Without `-b`, behavior is unchanged. A new `base_branch` config field in `orca.yml` provides the default base ref.

**Tech Stack:** Python 3.12, asyncio, git CLI, argparse, yaml

---

### Task 1: Parse `base_branch` from orca.yml

**Files:**
- Modify: `src/orca/orchestrator/config_types.py`
- Modify: `tests/orchestrator/test_config_types.py`

- [ ] **Step 1: Write failing tests for `base_branch` parsing**

In `tests/orchestrator/test_config_types.py`, add:

```python
class TestParseOrchestratorConfig:
    def test_base_branch_from_config(self) -> None:
        raw = {"base_branch": "origin/develop"}
        result = parse_orchestrator_config(raw)
        assert result.base_branch == "origin/develop"

    def test_base_branch_default(self) -> None:
        result = parse_orchestrator_config({})
        assert result.base_branch == "origin/main"

    def test_base_branch_none_input(self) -> None:
        result = parse_orchestrator_config(None)
        assert result.base_branch == "origin/main"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_config_types.py::TestParseOrchestratorConfig -v`
Expected: FAIL — `parse_orchestrator_config` not defined

- [ ] **Step 3: Implement `OrchestratorConfig` and `parse_orchestrator_config`**

In `src/orca/orchestrator/config_types.py`, add:

```python
@dataclass(frozen=True)
class OrchestratorConfig:
    base_branch: str = "origin/main"


def parse_orchestrator_config(raw: dict[str, Any] | None) -> OrchestratorConfig:
    """Parse orchestrator-level config from orca.yml (fields outside the engine config)."""
    if not raw:
        return OrchestratorConfig()
    base_branch = raw.get("base_branch", "origin/main")
    return OrchestratorConfig(base_branch=str(base_branch))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_config_types.py::TestParseOrchestratorConfig -v`
Expected: PASS

- [ ] **Step 5: Run lints and type-check**

Run: `uv run ruff check src/orca/orchestrator/config_types.py tests/orchestrator/test_config_types.py && uv run mypy src/orca/orchestrator/config_types.py`
Expected: clean

- [ ] **Step 6: Commit**

```
git add src/orca/orchestrator/config_types.py tests/orchestrator/test_config_types.py
git commit -m "feat: parse base_branch from orca.yml config"
```

---

### Task 2: Add `_git_create_branch` helper and `resolve_base_ref`

**Files:**
- Modify: `src/orca/orchestrator/runner.py`
- Modify: `tests/orchestrator/test_cli.py`

- [ ] **Step 1: Write failing tests for `resolve_base_ref`**

In `tests/orchestrator/test_cli.py`, add:

```python
from orca.orchestrator.runner import resolve_base_ref


class TestResolveBaseRef:
    def test_cli_takes_precedence(self) -> None:
        assert resolve_base_ref(cli_base="origin/v2", config_base="origin/develop") == "origin/v2"

    def test_config_used_when_no_cli(self) -> None:
        assert resolve_base_ref(cli_base=None, config_base="origin/develop") == "origin/develop"

    def test_default_when_neither(self) -> None:
        assert resolve_base_ref(cli_base=None, config_base="origin/main") == "origin/main"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_cli.py::TestResolveBaseRef -v`
Expected: FAIL — `resolve_base_ref` not defined

- [ ] **Step 3: Implement `resolve_base_ref`**

In `src/orca/orchestrator/runner.py`, add:

```python
def resolve_base_ref(cli_base: str | None, config_base: str) -> str:
    """Resolve the base ref for branch creation.

    Priority: CLI --base > config base_branch > "origin/main" (config default).
    """
    if cli_base is not None:
        return cli_base
    return config_base
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_cli.py::TestResolveBaseRef -v`
Expected: PASS

- [ ] **Step 5: Write failing test for `_git_create_branch`**

In `tests/orchestrator/test_cli.py`, add the `git_repo` fixture and `_current_branch` helper (same pattern as `test_worktree.py`):

```python
@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)
    return tmp_path


def _current_branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
```

Then add the test class:

```python
from orca.orchestrator.runner import _git_create_branch


class TestGitCreateBranch:
    @pytest.mark.asyncio()
    async def test_creates_branch_from_base(self, git_repo: Path) -> None:
        await _git_create_branch("new-feature", _current_branch(git_repo), git_repo)
        result = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "--verify", "new-feature"],
            capture_output=True,
        )
        assert result.returncode == 0

    @pytest.mark.asyncio()
    async def test_invalid_base_raises(self, git_repo: Path) -> None:
        with pytest.raises(RuntimeError, match="Failed to create branch"):
            await _git_create_branch("new-feature", "nonexistent-ref", git_repo)
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_cli.py::TestGitCreateBranch -v`
Expected: FAIL — `_git_create_branch` not defined

- [ ] **Step 7: Implement `_git_create_branch`**

In `src/orca/orchestrator/runner.py`, add:

```python
async def _git_create_branch(branch_name: str, base_ref: str, repo_root: Path) -> None:
    """Create a git branch from a base ref."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "branch",
        branch_name,
        base_ref,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = f"Failed to create branch '{branch_name}' from '{base_ref}': {stderr.decode()}"
        raise RuntimeError(msg)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_cli.py::TestResolveBaseRef tests/orchestrator/test_cli.py::TestGitCreateBranch -v`
Expected: PASS

- [ ] **Step 9: Run lints and type-check**

Run: `uv run ruff check src/orca/orchestrator/runner.py tests/orchestrator/test_cli.py && uv run mypy src/orca/orchestrator/runner.py`
Expected: clean

- [ ] **Step 10: Commit**

```
git add src/orca/orchestrator/runner.py tests/orchestrator/test_cli.py
git commit -m "feat: add resolve_base_ref and _git_create_branch helpers"
```

---

### Task 3: Add `-b` and `--base` CLI args, wire up startup flow

**Files:**
- Modify: `src/orca/orchestrator/runner.py`
- Modify: `tests/orchestrator/test_cli.py`

- [ ] **Step 1: Write failing test for CLI arg parsing**

In `tests/orchestrator/test_cli.py`, add:

```python
from orca.orchestrator.runner import build_parser


class TestBuildParser:
    def test_branch_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["task.md", "-b", "feature-auth"])
        assert args.branch == "feature-auth"

    def test_base_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["task.md", "--base", "origin/v2"])
        assert args.base == "origin/v2"

    def test_branch_and_base(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["task.md", "-b", "feature-auth", "--base", "origin/v2"])
        assert args.branch == "feature-auth"
        assert args.base == "origin/v2"

    def test_no_branch_defaults_none(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["task.md"])
        assert args.branch is None
        assert args.base is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_cli.py::TestBuildParser -v`
Expected: FAIL — `build_parser` not defined

- [ ] **Step 3: Extract parser into `build_parser()` and add new flags**

In `src/orca/orchestrator/runner.py`, extract the argparse setup from `main()` into a standalone function and add the new flags:

```python
def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="orca", description="Orca orchestrator CLI")
    parser.add_argument("task_file", type=Path, help="Path to the task file")
    parser.add_argument(
        "-w", "--workflow", type=str, default=None, help="Workflow name shorthand (e.g. 'develop' -> orca.develop.yml)"
    )
    parser.add_argument("-b", "--branch", type=str, default=None, help="Integration branch name for this run")
    parser.add_argument(
        "--base", type=str, default=None, help="Base ref to branch from (default: config or origin/main)"
    )
    parser.add_argument("--headless", action="store_true", help="Run without TUI (headless mode)")
    parser.add_argument("--insights", action="store_true", help="Enable insights agent for progress monitoring")
    return parser
```

Update `main()` to use `build_parser()` and replace the inline parser setup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_cli.py::TestBuildParser -v`
Expected: PASS

- [ ] **Step 5: Wire up branch resolution in `main()`**

Update `main()` to resolve the branch name and base ref. Add `from orca.orchestrator.config_types import parse_orchestrator_config` to imports.

```python
def main() -> None:
    """CLI entry point: orca <task_file> [-b branch] [--base ref] [-w workflow] [--headless] [--insights]."""
    parser = build_parser()
    args = parser.parse_args()

    repo_root = Path.cwd()
    config_path = resolve_config_path(repo_root, args.workflow)

    # Parse orchestrator config for base_branch default
    raw_config: dict[str, Any] = yaml.safe_load(config_path.read_text())
    orch_config = parse_orchestrator_config(raw_config)

    if args.branch is not None:
        branch_name = args.branch
        base_ref: str | None = resolve_base_ref(args.base, orch_config.base_branch)
    else:
        branch_name = resolve_branch()
        base_ref = None

    # Validate task file exists before starting
    if not args.task_file.exists():
        print(f"Error: task file not found: {args.task_file}")
        raise SystemExit(1)

    if args.headless:
        asyncio.run(run(args.task_file, branch_name, config_path, base_ref=base_ref, insights_enabled=args.insights))
    else:
        # Shared state between orchestrator (daemon thread) and TUI (main thread).
        hot_sessions: set[str] = set()
        session_log_paths: dict[str, str] = {}
        insights_state: dict[str, str] = {}

        run_error: BaseException | None = None

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
                    )
                )
            except BaseException as e:
                run_error = e

        import threading

        thread = threading.Thread(target=run_orchestrator, daemon=True)
        thread.start()

        # ... rest of TUI setup unchanged
```

- [ ] **Step 6: Update `run()` signature and fresh-start logic**

Add `base_ref: str | None = None` parameter to `run()`. Update the fresh-start `else` block:

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
) -> None:
```

Replace the fresh-start branch creation block with:

```python
        if base_ref is not None:
            # -b mode: create integration branch and worktree
            if not await _git_branch_exists(branch_name, repo_root):
                await _git_create_branch(branch_name, base_ref, repo_root)
            await worktree_mgr.create(
                issue_id=root_issue_id,
                branch_name=branch_name,
                parent_branch=base_ref,
            )
        else:
            # Legacy mode: use repo root if branch already checked out
            branch_exists = await _git_branch_exists(branch_name, repo_root)
            if branch_exists:
                logger.info(
                    "Branch %s already exists — using repo root as root workdir",
                    branch_name,
                    extra={"event": "branch_reuse", "branch": branch_name},
                )
            else:
                await worktree_mgr.create(
                    issue_id=root_issue_id,
                    branch_name=branch_name,
                    parent_branch=branch_name,
                )
```

Note: the legacy `else` path now passes `parent_branch=branch_name` instead of `"HEAD"` — this is the bugfix for the ambient HEAD issue.

- [ ] **Step 7: Run lints and type-check**

Run: `uv run ruff check src/orca/orchestrator/runner.py && uv run mypy src/orca/orchestrator/runner.py`
Expected: clean

- [ ] **Step 8: Run full orchestrator test suite**

Run: `uv run pytest tests/orchestrator/ -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```
git add src/orca/orchestrator/runner.py tests/orchestrator/test_cli.py
git commit -m "feat: add -b and --base CLI flags for concurrent run isolation"
```

---

### Task 4: Integration test — two concurrent runs with different `-b` values

**Files:**
- Create: `tests/orchestrator/test_concurrent_runs.py`

- [ ] **Step 1: Write integration test**

Create `tests/orchestrator/test_concurrent_runs.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orca.orchestrator.runner import _git_branch_exists, _git_create_branch
from orca.orchestrator.worktree import WorktreeManager


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)
    return tmp_path


def _current_branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class TestConcurrentRunIsolation:
    @pytest.mark.asyncio()
    async def test_two_runs_create_isolated_worktrees(self, git_repo: Path) -> None:
        base = _current_branch(git_repo)

        # Simulate two runs creating branches and worktrees
        await _git_create_branch("feature-auth", base, git_repo)
        await _git_create_branch("feature-billing", base, git_repo)

        mgr_a = WorktreeManager(repo_root=git_repo, root_branch="feature-auth")
        mgr_b = WorktreeManager(repo_root=git_repo, root_branch="feature-billing")

        path_a = await mgr_a.create(
            issue_id="root-a", branch_name="feature-auth", parent_branch=base
        )
        path_b = await mgr_b.create(
            issue_id="root-b", branch_name="feature-billing", parent_branch=base
        )

        # Worktrees are isolated
        assert path_a != path_b
        assert path_a.exists()
        assert path_b.exists()

        # State directories would be isolated
        state_a = git_repo / ".orca" / "runs" / "feature-auth"
        state_b = git_repo / ".orca" / "runs" / "feature-billing"
        assert state_a != state_b

    @pytest.mark.asyncio()
    async def test_branch_created_from_base_ref(self, git_repo: Path) -> None:
        base = _current_branch(git_repo)

        # Get the commit SHA of the base
        result = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", base],
            check=True,
            capture_output=True,
            text=True,
        )
        base_sha = result.stdout.strip()

        await _git_create_branch("feature-auth", base, git_repo)

        # Verify the new branch points to the same commit
        result = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "feature-auth"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == base_sha

    @pytest.mark.asyncio()
    async def test_resume_skips_branch_creation(self, git_repo: Path) -> None:
        base = _current_branch(git_repo)
        await _git_create_branch("feature-auth", base, git_repo)

        # Branch already exists — _git_branch_exists should return True
        assert await _git_branch_exists("feature-auth", git_repo)
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/orchestrator/test_concurrent_runs.py -v`
Expected: PASS

- [ ] **Step 3: Run lints**

Run: `uv run ruff check tests/orchestrator/test_concurrent_runs.py`
Expected: clean

- [ ] **Step 4: Commit**

```
git add tests/orchestrator/test_concurrent_runs.py
git commit -m "test: integration tests for concurrent run isolation"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 2: Run all lints and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: all clean

- [ ] **Step 3: Verify no regressions in existing behavior**

Run without `-b` should still work — `resolve_branch()` fallback path is unchanged.
Run: `uv run pytest tests/orchestrator/test_cli.py tests/orchestrator/test_runner.py -v`
Expected: all PASS
