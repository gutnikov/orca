# CLAUDE.md

## Project

Python 3.12 project using uv package manager. Source code lives in `src/orca/`.

Two packages:
- `src/orca/engine/` — pure state machine (reducer, config, types, dispatch). No I/O.
- `src/orca/orchestrator/` — async runtime (worker protocol, worktrees, persistence, CLI).

## Commands

- `uv sync` — install dependencies
- `uv run ruff check .` — lint
- `uv run ruff format --check .` — format check
- `uv run mypy src/` — type-check
- `uv run pytest` — run tests
- `orca run <task.md> <branch-name>` — run a workflow

## Code Style

- Ruff rules: E, F, I, UP, B, SIM
- Line length: 120
- Mypy: strict mode enabled
- All code must pass ruff and mypy before merge

## Architecture

The engine reducer is pure: `reduce(config, state, event, generate_id, now) -> (new_state, effects)`. It never does I/O. The orchestrator consumes `DispatchWorkerEffect`s by spawning Claude Code CLI subprocesses, then feeds `WorkerResultEvent`/`WorkerFailedEvent` back.

Key types: `StateMachineConfig`, `State`, `Event` (Create/Advance/WorkerResult/WorkerFailed), `Effect` (DispatchWorker/Error).

Worker config in `orca.yml`: `kind` (only "claude-code"), `prompt` (Jinja2 template path), optional `timeout`.

## CI

Self-hosted GitHub Actions runners. Two jobs: `lint` (ruff) and `type-check` (mypy).

## Documentation

Project documentation lives in `docs/`. See `docs/` subdirectories for specific topics.
