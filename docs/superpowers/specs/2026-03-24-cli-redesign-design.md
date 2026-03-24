# CLI Redesign

## Summary

Simplify the orca CLI by removing subcommands, making TUI the default mode, supporting multiple workflow files, and defaulting the branch to the current git branch.

**Before:**
```
orca run <task_file> <branch_name> [--headless] [--insights]
orca watch <branch_name>
```

**After:**
```
orca <task_file> [-b branch] [-w workflow] [--headless] [--insights]
```

## Changes

### 1. Remove subcommands, make task_file the root positional

Remove the `run` and `watch` argparse subparsers. The root parser takes `task_file` as a required positional argument.

`watch` is removed entirely — no replacement. Users who started headless check logs manually.

### 2. TUI is the default (already is, just remove `watch`)

`--headless` remains an opt-in flag (default false). This is already the behavior for `orca run`; the only change is removing the separate `watch` command that provided TUI-only mode.

### 3. Optional branch via `-b` / `--branch`

`branch_name` moves from a required positional to an optional flag: `-b` / `--branch`.

When omitted, default to the current git branch via `git rev-parse --abbrev-ref HEAD`. If this fails (detached HEAD, not a git repo), exit with a clear error asking the user to specify `-b`.

The branch still determines the run directory (`.orca/runs/{branch}/`). Running twice on the same branch resumes/overwrites — same semantics as today.

### 4. Workflow file selection via `-w` / `--workflow`

Add `-w` / `--workflow` flag that takes a shorthand name.

Resolution:
- Omitted: load `orca.yml` (current behavior)
- `-w develop`: load `orca.develop.yml`
- `-w test`: load `orca.test.yml`

The file is always resolved relative to the repo root. If the resolved file does not exist, exit with an error listing available `orca.*.yml` files in the repo root.

## Files to change

### `src/orca/orchestrator/runner.py`

This is the only source file that changes.

**Argparse rewrite** (~lines 276-330):
- Remove subparsers (`run`, `watch`)
- Add `task_file` as root positional (type=Path)
- Add `-b` / `--branch` as optional string
- Add `-w` / `--workflow` as optional string
- Keep `--headless` and `--insights` flags

**Config path resolution in `main()`:**

Resolve `config_path` in `main()` (where `args` is available), then pass it to `run()` as a `Path` parameter. This replaces the hardcoded `repo_root / "orca.yml"` inside `run()` (~line 151).

```python
workflow = args.workflow
config_name = f"orca.{workflow}.yml" if workflow else "orca.yml"
config_path = repo_root / config_name
```

If file missing, list available `orca*.yml` files (including bare `orca.yml`) in the error message.

The `run()` function signature changes from:
```python
async def run(task_file: Path, branch_name: str, insights_enabled: bool = False) -> None:
```
to:
```python
async def run(task_file: Path, branch_name: str, config_path: Path, insights_enabled: bool = False) -> None:
```

**TUI code path** (~lines 319-322):

The TUI branch in `main()` also loads `orca.yml` independently to pass to `OrcaApp`. This must use the same resolved `config_path` instead of hardcoding `orca.yml`.

**Branch default** (~line 157):
- If `args.branch` is None, run `git rev-parse --abbrev-ref HEAD` in `repo_root`
- If that returns `"HEAD"` (detached) or fails, exit with error

**Remove `_watch` function** (~lines 332-353):
- Delete the function and its subparser registration entirely.

### `CLAUDE.md`

Update the `orca run <task.md> <branch-name>` line under Commands to:
```
orca <task.md> [-b branch] [-w workflow] [--headless] [--insights]
```

### `README.md`

Update usage examples to reflect the new CLI syntax.

### Tests

Update any tests that invoke the CLI via argparse or test argument parsing. No engine or orchestrator tests should be affected since the interface between runner and orchestrator is unchanged.

## Out of scope

- No changes to the engine, reducer, config parser, orchestrator, TUI, or worker layers
- No changes to `orca.yml` format or validation
- No new subcommands
