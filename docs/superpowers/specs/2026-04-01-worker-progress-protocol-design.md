# Worker Progress Protocol Design

## Summary

Workers report progress (0–100%) and status text by emitting HTML comment markers in their terminal output. The orchestrator's existing scrollback capture loop parses these markers and updates the session manifest. The TUI and MCP consumers read progress from session data — no new APIs needed.

## Progress Marker Format

Workers emit a structured HTML comment to stdout:

```
<!-- PROGRESS: 68 | Exploring sidebar components... -->
```

- **Percent** (`68`): integer 0–100, required
- **Status** (`Exploring sidebar components...`): freeform text after `|`, optional
- If status is omitted, only the progress number is updated

**Regex**: `<!--\s*PROGRESS:\s*(\d{1,3})\s*(?:\|\s*(.*?))?\s*-->`

The parser scans the full scrollback and takes the **last** match — earlier markers are superseded.

## Configuration

Progress reporting is opt-in per worker state via a `progress` flag on the worker definition:

```yaml
# orca.yml
implementing:
  worker:
    kind: claude-code
    prompt: prompts/implementing.md
    timeout: 1200
    progress: true          # enables progress reporting
    result_format:
      ...
```

When `progress` is not set or `false`, no prompt injection occurs and no scrollback parsing is performed for that worker.

## Prompt Injection

When `progress: true`, the template engine appends a standard instruction block after the user's prompt template. This is inserted in `template.py` at the same point where the result.json instruction is already appended.

Injected block:

```markdown
## Progress Reporting

As you work, periodically report your progress by outputting an HTML comment:

<!-- PROGRESS: <percent> | <status> -->

- <percent> is an integer from 0 to 100
- <status> is a short description of what you're currently doing
- Emit this after completing meaningful milestones, not on every action
- Example: <!-- PROGRESS: 25 | Writing unit tests for auth module -->
```

## Parsing Pipeline

Progress parsing hooks into the existing scrollback capture loop in `orchestrator.py` (`_session_capture_loop`), which already runs at:
- 0.5s intervals for hot sessions (TUI-selected)
- 10s intervals for cold sessions

### New function: `parse_progress(scrollback: str) -> tuple[int, str | None] | None`

Located in `src/orca/orchestrator/worker.py` (alongside existing worker utilities).

```python
import re

_PROGRESS_RE = re.compile(r"<!--\s*PROGRESS:\s*(\d{1,3})\s*(?:\|\s*(.*?))?\s*-->")

def parse_progress(scrollback: str) -> tuple[int, str | None] | None:
    """Parse the last progress marker from scrollback text.
    
    Returns (percent, status) or None if no marker found.
    """
    matches = _PROGRESS_RE.findall(scrollback)
    if not matches:
        return None
    percent_str, status = matches[-1]
    percent = min(int(percent_str), 100)
    return (percent, status.strip() or None)
```

### Integration in capture loop

After writing the scrollback to the log file, the orchestrator calls `parse_progress()` on the captured text. If a result is returned and differs from the current session values, it updates the session manifest:

```python
# In _session_capture_loop, after writing log file:
if effect_has_progress:  # only if worker config has progress: true
    result = parse_progress(scrollback)
    if result is not None:
        percent, status = result
        session_manifest.update_progress(session_id, percent, status)
```

The `effect_has_progress` flag is derived from the `DispatchWorkerEffect` — the effect already carries all worker config context.

## Session Manifest Changes

Three new optional fields on each session entry in `sessions.json`:

| Field                | Type          | Description                                          |
|----------------------|---------------|------------------------------------------------------|
| `progress`           | `int \| None` | 0–100, last parsed from scrollback                   |
| `status`             | `str \| None` | Freeform text from marker                            |
| `progress_updated_at`| `str \| None` | ISO 8601 timestamp of last progress update           |

### New method on SessionManifest: `update_progress`

```python
def update_progress(self, session_id: str, progress: int, status: str | None) -> None:
    """Update progress and status for a session."""
    for entry in self._entries:
        if entry.get("session_id") == session_id:
            entry["progress"] = progress
            entry["status"] = status
            entry["progress_updated_at"] = datetime.now(UTC).isoformat()
            self._persist()
            break
```

## DispatchWorkerEffect Changes

Add a `progress_enabled` field to `DispatchWorkerEffect` so the orchestrator knows which sessions to parse:

| Field              | Type   | Description                                |
|--------------------|--------|--------------------------------------------|
| `progress_enabled` | `bool` | Whether this worker has `progress: true`   |

This is set by the dispatch logic in `dispatch.py` from the `WorkerDef` config.

## WorkerDef Changes

Add a `progress` field to `WorkerDef` in `types.py`:

| Field      | Type   | Default | Description                    |
|------------|--------|---------|--------------------------------|
| `progress` | `bool` | `False` | Enable progress reporting      |

Parsed from `orca.yml` by `config.py`.

## Staleness Detection

When `progress_updated_at` is set and more than **60 seconds** old (relative to current time), the progress is considered stalled.

- Staleness is a **UI-only concern** — computed in `PhasesPanel._render_phases()` at render time
- No staleness field is stored in the session manifest
- The threshold is a constant in `phases_panel.py`: `_PROGRESS_STALE_SECONDS = 60`
- When stalled: bar and percentage render in dim color, status text gets `(stalled)` suffix
- Automatically clears when the next progress marker is parsed (updates `progress_updated_at`)

## MCP Exposure

No new MCP tools needed. The existing `orca_get_run` returns session data including all fields. Adding `progress`, `status`, and `progress_updated_at` to the session dict automatically exposes them. Consumers can read:

```json
{
  "session_id": "abc-123",
  "state": "implementing",
  "progress": 68,
  "status": "Exploring sidebar components...",
  "progress_updated_at": "2026-04-01T12:30:00+00:00",
  "started_at": "2026-04-01T12:17:12+00:00",
  "completed_at": null
}
```

## What This Spec Does NOT Cover

- TUI rendering of progress bars — covered in `2026-04-01-worker-progress-ui-design.md`
- Progress aggregation across workers for a single issue
- Custom progress marker formats per workflow
