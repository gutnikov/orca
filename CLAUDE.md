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
- `orca <task.md> [-w workflow] [--headless] [--insights]` — run a workflow

## Code Style

- Ruff rules: E, F, I, UP, B, SIM
- Line length: 120
- Mypy: strict mode enabled
- All code must pass ruff and mypy before merge

## Architecture

The engine reducer is pure: `reduce(config, state, event, generate_id, now) -> (new_state, effects)`. It never does I/O. The orchestrator consumes `DispatchWorkerEffect`s by spawning Claude Code CLI subprocesses, then feeds `WorkerResultEvent`/`WorkerFailedEvent` back.

Key types: `StateMachineConfig`, `State`, `Event` (Create/Advance/WorkerResult/WorkerFailed), `Effect` (DispatchWorker/Error).

Built-in states: `done` (success terminal) and `failed` (triggers worker failure/retry semantics). Never defined in `states:` block — always available as transition targets.

Built-in outcome: `waiting` — worker writes `{"outcome": "waiting"}` to pause its session and timer until manually unblocked via `orca unblock`. Intercepted by the orchestrator before result validation. Not declared in workflow configs.

Worker config in `orca.yml`: `kind` (only "claude-code"), `prompt` (Jinja2 template path), optional `timeout`.

## CI

Self-hosted GitHub Actions runners. Two jobs: `lint` (ruff) and `type-check` (mypy).

## Documentation

Project documentation lives in `docs/`. See `docs/` subdirectories for specific topics.

## Skills

Skills live in `skills/` and are invoked by reading their `SKILL.md` with the Read tool (NOT via the Skill tool — these are project-local skills, not registered slash commands).

- `skills/orca-manager/SKILL.md` — Autonomous orca workflow management. Read this before starting, monitoring, diagnosing, or chaining orca workflow runs.
- `skills/orca-workflow-builder/SKILL.md` — Orca workflow authoring. Read this when creating, updating, or auditing orca workflows and prompt templates.
