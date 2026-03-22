# Session Sync Design

## Overview

The orchestrator periodically renders worker session transcripts to markdown files so that the orca user can browse `.orca/transcripts/` to inspect worker progress, reasoning, and failures — during or after a run.

## How It Works

### Session Manifest

The orchestrator (not the worker) maintains a manifest of all sessions in:

```
.orca/runs/{branch}/sessions.json
```

Each entry:

```json
{
  "issue_id": "abc-123",
  "state": "implementing",
  "session_id": "ca4cc24d-fd9a-4098-872f-634e75c4379a",
  "worktree_path": "/Users/.../orca/.orca/worktrees/my-feature/db",
  "started_at": "2026-03-22T10:36:00Z",
  "completed_at": null
}
```

**Write ownership:** The orchestrator is the sole writer of this file — not the workers. This avoids concurrent-write hazards since reducer calls (and manifest updates) are serialized in the orchestrator's event loop. The flow:

1. Worker extracts `session_id` from Claude's stream-json output by scanning for the first JSON object with `"type": "system"` and `"subtype": "init"` (not assuming it's the first line — there may be preamble like hook events).
2. Worker returns `session_id` to the orchestrator (via `WorkerOutcome` or an initialization callback).
3. Orchestrator appends the manifest entry.
4. When the orchestrator receives a `WorkerOutcome`, it sets `completed_at` on the corresponding entry.

### Sync Task

A background `asyncio.Task` in the orchestrator runs every 3 minutes:

1. Read `sessions.json`.
2. For each entry, find the native transcript at `~/.claude/projects/{project-hash}/{session_id}.jsonl`.
3. Run `claude-code-log` to render it to markdown:
   ```
   uv tool run claude-code-log {transcript_path} --format md -o {output_path}
   ```
4. Write output to `.orca/transcripts/{issue_id}/{state}-{timestamp}.md`.
5. **Skip logic:** If `completed_at` is set and the `.md` file exists, skip (session is done and already rendered). If `completed_at` is null (still running), always re-render to capture progress.

A final sync runs when the orchestrator exits (after all workers complete) to catch any sessions that finished between the last periodic sync and shutdown.

### Project Path Resolution

Claude Code stores native transcripts at:

```
~/.claude/projects/{project-hash}/{session_id}.jsonl
```

The `{project-hash}` is derived from the working directory by replacing `/` with `-`. For example:

```
/Users/agutnikov/work/orca → -Users-agutnikov-work-orca
```

Since workers run in worktrees under `.orca/worktrees/{branch}/`, the project hash is based on the worktree path, not the repo root. The sync task derives this from the `worktree_path` recorded in the manifest.

**Fragility note:** This path-mangling algorithm is observed behavior, not a documented Claude Code API. If it changes, the sync task will fail to find transcripts. As a fallback, the sync task scans `~/.claude/projects/` for directories containing the target `{session_id}.jsonl` file if the derived path does not exist.

### Output Structure

```
.orca/transcripts/
├── abc-123/
│   ├── planning-2026-03-22T10-35-00.md
│   └── implementing-2026-03-22T10-36-00.md
└── def-456/
    └── implementing-2026-03-22T10-40-00.md
```

Named `.orca/transcripts/` (not `.orca/sessions/`) to distinguish from the raw stream-json session logs at `{worktree}/.orca/sessions/` defined in the worker protocol spec.

Files accumulate across the run lifetime. No automatic cleanup.

## Changes to Existing Modules

### `worker.py` — ClaudeCodeWorker

Add session ID capture:

1. While reading stream-json lines, scan for the first `{"type": "system", "subtype": "init", ...}` message and extract `session_id`.
2. Return `session_id` to the orchestrator alongside the `WorkerOutcome` (add a `session_id: str | None` field to `WorkerSuccess` and `WorkerFailure`).

The worker does **not** write to `sessions.json` — the orchestrator owns that file.

### `orchestrator.py` — Orchestrator

1. After spawning a worker task and receiving the session ID, append to `sessions.json`.
2. On `WorkerOutcome`, set `completed_at` on the manifest entry.
3. Start `_sync_sessions_loop` as background task, cancel on shutdown after final sync.

```python
async def _sync_sessions_loop(self) -> None:
    """Periodically render session transcripts to markdown."""
    while True:
        await asyncio.sleep(180)  # 3 minutes
        await self._sync_sessions()
```

### New: `orchestrator/session_sync.py`

Encapsulates the sync logic:

```python
class SessionSync:
    def __init__(self, run_dir: Path, transcripts_dir: Path):
        self.run_dir = run_dir             # .orca/runs/{branch}/
        self.transcripts_dir = transcripts_dir  # .orca/transcripts/

    async def sync(self) -> None:
        """Read manifest, render new/updated transcripts to markdown."""

    def _claude_projects_path(self, worktree_path: Path) -> Path:
        """Derive ~/.claude/projects/{hash}/ from worktree path.
        Falls back to scanning ~/.claude/projects/ if derived path missing."""

    def _output_path(self, issue_id: str, state: str, started_at: str) -> Path:
        """Build .orca/transcripts/{issue_id}/{state}-{timestamp}.md"""

    def _needs_render(self, entry: dict) -> bool:
        """True if session is still running or completed but not yet rendered."""
```

## Dependencies

- `claude-code-log` Python package (installed via `uv tool install claude-code-log`).
- Invoked as `uv tool run claude-code-log` — no import, subprocess only.

## Edge Cases

- **Worker still running:** The native transcript is written incrementally. Rendering mid-session produces a partial markdown. The next sync cycle re-renders it (since `completed_at` is still null).
- **Session ID not found:** If no `system/init` message appears in the stream-json output, `session_id` is `None` in the `WorkerOutcome`. The orchestrator logs a warning and skips manifest entry. The session won't be synced but the worker continues normally.
- **`claude-code-log` fails on a specific file:** Skip that entry, log the error, continue with remaining entries. Only disable the sync task globally if the `claude-code-log` binary is not found.
- **Multiple runs:** Each run has its own `sessions.json` under `.orca/runs/{branch}/`. The shared `.orca/transcripts/` directory may contain files from multiple runs — this is fine, issue IDs are unique.
- **Re-dispatched sessions (crash recovery):** A re-dispatched worker produces a new `session_id`. Both the original and retried sessions appear in the manifest with different timestamps, producing separate markdown files. Stale entries from pre-crash sessions are kept as historical artifacts.
