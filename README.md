# Orca

A state machine engine and orchestrator for driving issue lifecycle through configurable workflows. Workers (currently Claude Code CLI agents) process issues in each state, and the engine routes them based on outcomes.

## Quick Start

```bash
uv sync
orca run task.md my-feature-branch
```

## How It Works

1. Define a workflow in `orca.yml` — states, transitions, worker prompts, and result schemas
2. Write a task file — first line is title, rest is description
3. Run `orca run task.md branch-name` — creates a branch, spawns workers, runs to completion

The engine is a pure reducer: `reduce(config, state, event) -> (new_state, effects)`. The orchestrator consumes effects, spawns Claude Code subprocesses, and feeds results back. Each issue gets its own git worktree for isolation.

## Project Structure

```
src/orca/
  engine/         # Pure state machine — reducer, config, types, dispatch
  orchestrator/   # Async runtime — worker protocol, worktrees, CLI
```

## Commands

```bash
uv sync                        # install dependencies
uv run pytest                  # run tests
uv run ruff check .            # lint
uv run ruff format --check .   # format check
uv run mypy src/               # type-check
```

## Documentation

See [docs/](docs/) for detailed documentation, specs, and plans.
