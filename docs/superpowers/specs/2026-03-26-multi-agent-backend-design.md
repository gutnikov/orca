# Multi-Agent Backend: OpenCode + Claude Code

**Date:** 2026-03-26
**Status:** Approved

## Problem

Orca workers are hardcoded to the Claude Code CLI. The `ClaudeCodeWorker` class hardcodes the `claude` binary, its flags (`--dangerously-skip-permissions --max-turns 50`), and stdin-based prompt delivery. Users cannot use alternative CLI agents like OpenCode within the same workflow.

## Goal

Allow per-state worker kind selection in `orca.yml`, so different states in the same workflow can use different CLI agents (Claude Code, OpenCode, or future agents).

## Design: Config-Driven Generic CLI Worker (Approach B)

Replace `ClaudeCodeWorker` with a single `CliAgentWorker` class driven by a `KindConfig` registry. Each worker kind is a config entry describing CLI invocation differences. All shared logic (tmux, result polling, grace period, timeouts) stays in one place.

### 1. Config Changes

#### orca.yml

The `worker` block gains optional `model` and `args` fields:

```yaml
states:
  scoping:
    worker:
      kind: opencode
      prompt: prompts/scoping.md
      timeout: 600
      model: anthropic/claude-sonnet-4-5   # optional, passed as -m to opencode
      args: ["--max-turns", "100"]          # optional, overrides/extends defaults
      result_format:
        outcome:
          type: enum
          values: [decompose, ready]
```

- `model` is optional. OpenCode uses it via `-m`. Claude Code ignores it (model comes from its own config).
- `args` is optional. Appended after default args. User's responsibility to manage conflicts with defaults.

#### WorkerDef type (`engine/types.py`)

```python
@dataclass(frozen=True)
class WorkerDef:
    kind: str
    prompt: str
    result_format: dict[str, ResultFormatField]
    timeout: int | None = None
    inactivity_timeout: int | None = None
    model: str | None = None         # NEW
    args: tuple[str, ...] | None = None    # NEW
```

#### Config validation (`engine/config.py`)

Replace the hardcoded `kind == "claude-code"` check (line 161) with an allowed-set check:

```python
_ALLOWED_WORKER_KINDS = {"claude-code", "opencode"}

if state.worker.kind not in _ALLOWED_WORKER_KINDS:
    msg = f"Worker for state '{name}': kind must be one of {_ALLOWED_WORKER_KINDS}, got '{state.worker.kind}'"
    raise ConfigValidationError(msg)
```

Parse `model` and `args` from the worker YAML block alongside existing fields.

### 2. Kind Config Registry (`orchestrator/worker.py`)

```python
@dataclass(frozen=True)
class KindConfig:
    bin: str                            # "claude" or "opencode"
    prompt_via: str                     # "stdin" or "arg"
    subcommand: str | None = None       # None for claude, "run" for opencode
    default_args: tuple[str, ...] = ()

KIND_REGISTRY: dict[str, KindConfig] = {
    "claude-code": KindConfig(
        bin="claude",
        prompt_via="stdin",
        default_args=("--dangerously-skip-permissions", "--max-turns", "50"),
    ),
    "opencode": KindConfig(
        bin="opencode",
        prompt_via="arg",
        subcommand="run",
        default_args=(),
    ),
}
```

### 3. Generic CliAgentWorker (`orchestrator/worker.py`)

Replaces `ClaudeCodeWorker`. Single class that handles all CLI-based agents.

**Constructor:** `CliAgentWorker(repo_root: Path, kind_config: KindConfig)`

**Command assembly in `execute()`:**

```python
cmd_parts: list[str] = [self._kind_config.bin]
if self._kind_config.subcommand:
    cmd_parts.append(self._kind_config.subcommand)
if self._kind_config.prompt_via == "arg":
    cmd_parts.append(prompt)
cmd_parts.extend(self._kind_config.default_args)
if extra_args:
    cmd_parts.extend(extra_args)
if model:
    cmd_parts.extend(["-m", model])

await pty_session.spawn(
    cmd_parts[0],
    cmd_parts[1:],
    cwd=workdir,
    stdin_data=prompt.encode() if self._kind_config.prompt_via == "stdin" else None,
    env=env,
)
```

**Result commands per kind:**

| | Claude Code | OpenCode |
|---|---|---|
| Command | `claude --dangerously-skip-permissions --max-turns 50` | `opencode run "<prompt>" -m provider/model` |
| Prompt delivery | stdin | Positional argument |
| Permissions | `--dangerously-skip-permissions` | Auto-approved in `run` mode |
| Max turns | `--max-turns 50` (default) | No equivalent (external timeout) |

Result file polling, grace period (30s), and timeout logic are identical across all kinds.

### 4. Worker Protocol Change

`execute()` gains two optional parameters:

```python
class Worker(Protocol):
    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: PtySession | None = None,
        env: dict[str, str] | None = None,
        model: str | None = None,            # NEW
        extra_args: list[str] | None = None,  # NEW
    ) -> WorkerOutcome: ...
```

### 5. Orchestrator Changes (`orchestrator/orchestrator.py`)

`_spawn_worker` passes `model` and `args` from the `WorkerDef` to the worker:

```python
worker_kind = state_def.worker.kind
worker = self.workers.get(worker_kind)
# ... existing tracking/backoff logic ...
# Pass model and args to _run_worker → worker.execute()
```

The `_run_worker` method passes `model=state_def.worker.model` and `extra_args=state_def.worker.args` through to `worker.execute()`.

### 6. Runner Changes (`orchestrator/runner.py`)

Build all workers from the registry instead of a single `ClaudeCodeWorker`:

```python
from orca.orchestrator.worker import CliAgentWorker, KIND_REGISTRY

workers = {name: CliAgentWorker(repo_root, config) for name, config in KIND_REGISTRY.items()}

orchestrator = Orchestrator(
    ...
    workers=workers,
    ...
)
```

## Out of Scope

- **Engine layer** (reducer, dispatch, effects) — no changes. `DispatchWorkerEffect` stays as-is.
- **Prompt templates** — agent-agnostic, shared across kinds.
- **TUI** — doesn't know about worker kinds.
- **Runtime binary validation** — no check if `opencode` binary exists. Fail naturally.
- **Per-kind result format** — same JSON file protocol for all kinds.

## Files Touched

1. `src/orca/engine/types.py` — add `model`, `args` to `WorkerDef`
2. `src/orca/engine/config.py` — parse new fields, relax kind validation to allowed set
3. `src/orca/orchestrator/worker.py` — replace `ClaudeCodeWorker` with `CliAgentWorker` + `KindConfig` + `KIND_REGISTRY`
4. `src/orca/orchestrator/orchestrator.py` — pass `model`/`args` through `_spawn_worker` to worker
5. `src/orca/orchestrator/runner.py` — build workers from registry
6. Tests — config parsing (new fields, kind validation), worker command assembly
