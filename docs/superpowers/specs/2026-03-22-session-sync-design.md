# Session Sync Design

## Overview

The orchestrator periodically renders worker session transcripts to markdown files so that the orca user can browse `.orca/sessions/` to inspect worker progress, reasoning, and failures — during or after a run.

## How It Works

### Session Manifest

When the `ClaudeCodeWorker` spawns a Claude subprocess, it records the session in a manifest file:

```
.orca/runs/{branch}/sessions.json
```

Each entry:

```json
{
  "issue_id": "abc-123",
  "state": "implementing",
  "session_id": "ca4cc24d-fd9a-4098-872f-634e75c4379a",
  "started_at": "2026-03-22T10:36:00Z"
}
```

The `session_id` is extracted from Claude's stream-json output — the `system/init` message includes `session_id`. The worker appends to this file after reading the first stream-json line.

### Sync Task

A background `asyncio.Task` in the orchestrator runs every 3 minutes:

1. Read `sessions.json`.
2. For each entry, find the native transcript at `~/.claude/projects/{project-hash}/{session_id}.jsonl`.
3. Run `claude-code-log` to render it to markdown:
   ```
   uv tool run claude-code-log {transcript_path} --format md -o {output_path}
   ```
4. Write output to `.orca/sessions/{issue_id}/{state}-{timestamp}.md`.
5. Skip entries where the `.md` file already exists and is newer than the source `.jsonl`.

A final sync runs when the orchestrator exits (after all workers complete) to catch any sessions that finished between the last periodic sync and shutdown.

### Project Path Resolution

Claude Code stores native transcripts at:

```
~/.claude/projects/{project-hash}/{session_id}.jsonl
```

The `{project-hash}` is derived from the working directory by replacing `/` with `-` and stripping the leading `-`. For example:

```
/Users/agutnikov/work/orca → -Users-agutnikov-work-orca
```

Since workers run in worktrees under `.orca/worktrees/{branch}/`, the project hash will be based on the worktree path, not the repo root. The sync task derives this from the worktree path recorded in the manifest (or from `WorktreeManager.resolve()`).

### Output Structure

```
.orca/sessions/
├── abc-123/
│   ├── planning-2026-03-22T10-35-00.md
│   └── implementing-2026-03-22T10-36-00.md
└── def-456/
    └── implementing-2026-03-22T10-40-00.md
```

Files accumulate across the run lifetime. No automatic cleanup.

## Changes to Existing Modules

### `worker.py` — ClaudeCodeWorker

Add session ID capture and manifest writing:

1. After spawning the subprocess and reading the first stream-json line, extract `session_id` from the `system/init` message.
2. Append `{issue_id, state, session_id, started_at}` to `.orca/runs/{branch}/sessions.json`.
3. Store the worktree path in the manifest entry (needed for project-hash resolution).

### `orchestrator.py` — Orchestrator

Add a `_sync_sessions` background task:

```python
async def _sync_sessions_loop(self) -> None:
    """Periodically render session transcripts to markdown."""
    while True:
        await asyncio.sleep(180)  # 3 minutes
        await self._sync_sessions()

async def _sync_sessions(self) -> None:
    """Render any new/updated session transcripts."""
    ...
```

The loop is started as an `asyncio.Task` alongside the main event loop and cancelled on shutdown (after a final `_sync_sessions()` call).

### New: `orchestrator/session_sync.py`

Encapsulates the sync logic:

```python
class SessionSync:
    def __init__(self, run_dir: Path, sessions_dir: Path):
        self.run_dir = run_dir       # .orca/runs/{branch}/
        self.sessions_dir = sessions_dir  # .orca/sessions/

    async def sync(self) -> None:
        """Read manifest, render new transcripts to markdown."""

    def _claude_projects_path(self, worktree_path: Path) -> Path:
        """Derive ~/.claude/projects/{hash}/ from worktree path."""

    def _output_path(self, issue_id: str, state: str, started_at: str) -> Path:
        """Build .orca/sessions/{issue_id}/{state}-{timestamp}.md"""

    def _needs_render(self, source: Path, target: Path) -> bool:
        """True if target doesn't exist or source is newer."""
```

## Dependencies

- `claude-code-log` Python package (installed via `uv tool install claude-code-log`).
- Invoked as `uv tool run claude-code-log` — no import, subprocess only.

## Edge Cases

- **Worker still running:** The native transcript is written to incrementally by Claude Code. Rendering mid-session produces a partial markdown file. The next sync cycle overwrites it with a more complete version (since the source `.jsonl` will be newer).
- **Session ID not found:** If the first stream-json line doesn't contain `session_id` (unexpected), log a warning and skip manifest entry. The session won't be synced but the worker continues normally.
- **`claude-code-log` not installed:** The sync task logs an error on first failure and disables itself for the rest of the run. Worker execution is unaffected.
- **Multiple runs:** Each run has its own `sessions.json` under `.orca/runs/{branch}/`. The shared `.orca/sessions/` directory may contain files from multiple runs — this is fine, issue IDs are unique.
