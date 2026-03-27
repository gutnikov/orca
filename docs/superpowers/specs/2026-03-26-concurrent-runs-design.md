# Concurrent Runs via `-b` Flag

## Problem

Running two orca processes simultaneously in the same repo breaks because:

- State files (state.json, branches.json, sessions.json) are keyed by the current git branch, so two runs on the same branch corrupt each other.
- The root issue reuses the repo root working directory, so only one run can occupy it.
- `resolve_branch()` reads HEAD implicitly — there's no way to specify which branch a run should use.
- `parent_branch="HEAD"` is passed when creating the root worktree, which is ambient and mutable.

## Solution

Add a `-b <branch>` CLI flag that creates an isolated integration branch and worktree for each run. Two runs with different `-b` values can execute concurrently.

## CLI Interface

```
orca task.md -b feature-auth                    # base from config or origin/main
orca task.md -b feature-auth --base origin/v2   # explicit base override
orca task.md                                    # no -b: today's behavior unchanged
```

## Config

New optional `base_branch` field in `orca.yml`:

```yaml
base_branch: origin/main   # optional, defaults to "origin/main"
```

Resolution order for the base ref: `--base` CLI flag > `base_branch` in orca.yml > `"origin/main"` fallback.

## Startup Flow

### With `-b feature-auth`

1. Resolve `base_ref` from `--base` / config / `"origin/main"` fallback.
2. Create git branch `feature-auth` pointing at `base_ref` (skip if branch already exists — this is the resume case).
3. Create worktree at `.orca/worktrees/feature-auth/` on that branch.
4. Root issue maps to `feature-auth`, works in that worktree (not repo root).
5. State files live in `.orca/runs/feature-auth/` as before.
6. Child issues branch from `feature-auth` (e.g., `feature-auth-fix-login`).

### Without `-b`

Unchanged — `resolve_branch()` reads HEAD, root issue uses repo root. Single-run-at-a-time limitation remains for this mode.

## Code Changes

### 1. `runner.py:main()` — CLI args

Add `-b` and `--base` to argparse:

```python
parser.add_argument("-b", "--branch", type=str, default=None, help="Integration branch name for this run")
parser.add_argument("--base", type=str, default=None, help="Base ref to branch from (default: config or origin/main)")
```

Branch resolution:

```python
if args.branch:
    branch_name = args.branch
else:
    branch_name = resolve_branch()  # today's behavior
```

### 2. `config_types.py` — parse `base_branch`

Add `base_branch` to the top-level config parsing. It is not part of the engine's `StateMachineConfig` — it's an orchestrator-level setting parsed alongside `integrations`.

### 3. `runner.py:run()` — accept and use `base_ref`

New parameter: `base_ref: str | None`. When `base_ref` is set (i.e., `-b` was used):

- On fresh start: create the integration branch from `base_ref`, then create a worktree for it. Do NOT fall through to the "branch exists, use repo root" path.
- Pass `base_ref` instead of `"HEAD"` to `worktree_mgr.create()`.
- On resume: branch and worktree already exist, load state as before.

```python
# Fresh start with -b
if base_ref is not None:
    if not await _git_branch_exists(branch_name, repo_root):
        # New helper: runs "git branch <name> <base_ref>"
        await _git_create_branch(branch_name, base_ref, repo_root)
    await worktree_mgr.create(
        issue_id=root_issue_id,
        branch_name=branch_name,
        parent_branch=base_ref,
    )
```

New async helper `_git_create_branch(name, base_ref, repo_root)` — runs `git branch <name> <base_ref>`. Errors if the base ref doesn't exist.

### 4. Fix `parent_branch="HEAD"` in existing fresh-start path

Even without `-b`, the current code passes `"HEAD"` when creating worktrees for the root issue. This should use the resolved branch name (from `resolve_branch()`), not the ambient HEAD. This is a bugfix independent of the `-b` feature but addressed here.

## What This Doesn't Solve

- **Git lock contention**: Two concurrent `git worktree add` calls can race on `.git/index.lock`. Git's own locking prevents corruption (one call errors), and worktree creation is fast and infrequent. Retry-with-backoff can be added later if needed.
- **Tmux session scoping**: Sessions already use UUIDs, no collision. Cleanup is per-process.
- **Cross-run merge conflicts**: Both runs branch from the same base. When run A merges back, run B may have conflicts. This is normal git workflow, not an orca-specific problem.

## Testing

- Unit test: `resolve_base_ref(cli_base, config_base)` returns correct priority.
- Integration test: two concurrent `run()` calls with different `-b` values produce isolated state directories and worktrees.
- Manual: run two orca processes with `-b` on the same repo, verify no errors.
