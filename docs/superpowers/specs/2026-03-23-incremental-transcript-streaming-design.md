# Incremental Transcript Streaming

## Problem

The TUI transcript viewer has high latency — users wait minutes to see worker activity.

Root causes:
1. `_sync_sessions_loop` runs every 180 seconds
2. Each sync re-reads the entire JSONL transcript and re-renders all entries to markdown
3. The TUI only reads the .md file on user interaction (clicking a session leaf), with no auto-refresh

For a 10-minute worker session, a user clicking an active session may see nothing or stale content.

## Design

### Incremental Renderer

Claude Code writes JSONL transcripts append-only — new entries are always added at the end. We exploit this by tracking how far we've rendered and only processing new entries.

**New function in `transcript.py`:**

```python
def render_incremental(
    jsonl_path: Path, byte_offset: int, last_type: str
) -> tuple[str, int, str]:
    """Read new JSONL entries from byte_offset, render to markdown.

    Returns:
        (new_markdown, new_byte_offset, new_last_type)
    """
```

This reads from `byte_offset`, parses each complete line, renders the entries using the existing `_render_entries` logic, and returns the new markdown fragment, the updated offset, and the updated `last_type`.

The existing `render_transcript` function stays unchanged for one-shot rendering of completed sessions.

**Byte offset tracking:** The new offset must be set to the byte position **after the last successfully parsed line's newline**, not EOF. This ensures truncated lines (from mid-write reads) are re-read on the next cycle.

**Continuity between chunks:** The existing renderer tracks `last_type` to insert `---` separators between consecutive `assistant` entries. The incremental renderer accepts `last_type` from the previous call and returns the updated value.

**Chunk joining:** When the new fragment will be appended to an existing .md file, it must be joined with `"\n\n"`. The `render_incremental` function returns the raw fragment; the caller (`_sync_entry`) prepends `"\n\n"` when appending to a non-empty file.

### Session Sync Changes

**`SessionSync` gains per-session tracking state:**

```python
@dataclass
class _SessionRenderState:
    byte_offset: int = 0
    last_type: str = ""
```

Stored in-memory on the `SessionSync` instance as `dict[str, _SessionRenderState]` keyed by session_id. No need to persist to disk — on restart, offset=0 triggers a full re-render (same as current behavior).

**On restart (offset=0 with existing .md file):** Truncate the .md file before re-rendering. This avoids doubled content.

**`_sync_entry` changes:**

- For active sessions (`completed_at is None`): call `render_incremental` with stored offset and `last_type`. If the .md file exists and has content, append with `"\n\n"` join. Otherwise write fresh. Update stored state.
- For completed sessions with no .md file: full render via `render_transcript` (existing behavior).
- For completed sessions with an existing .md file: do one final incremental render to capture any trailing entries, then stop syncing this session.

**File size guard:** Before reading from `byte_offset`, check that the JSONL file size >= offset. If the file is smaller (unlikely — would mean file replacement/truncation), reset offset to 0 and truncate the .md file.

### Sync Interval

Change `_sync_sessions_loop` interval from 180s to **5s**.

Only active sessions (where `completed_at is None`) need syncing each cycle. Completed sessions that have already been rendered are skipped entirely via the existing `needs_render` check.

At 5s intervals with incremental reads, each sync cycle only processes a few KB of new JSONL data per active session — negligible I/O.

### TUI Auto-Refresh

**`OrcaApp` owns the transcript poll timer** (matching the existing pattern where `OrcaApp` owns all timers and pushes updates to widgets via messages).

When a `WorkerRunSelected` message is received for an active session, `OrcaApp` starts a 3s interval timer that:
1. Stats the .md file for mtime changes
2. If changed, posts an update to `IssueDetail` to re-read and refresh
3. Stops when the user navigates away (different node selected) or the session completes

**Detecting active vs completed:** Add `active: bool` to `WorkerRunSelected` message. The tree widget sets this based on `session.get("completed_at") is None`.

**Scroll behavior:** Auto-scroll to bottom only if the user was already at the bottom (within a small threshold). If they've scrolled up to read earlier content, don't jump them.

### Data Flow

```
Claude Code CLI
    |  (appends JSONL entries as work happens)
    v
~/.claude/projects/{hash}/{session_id}.jsonl
    |  (SessionSync reads new bytes every 5s)
    v
render_incremental(path, offset, last_type) -> new markdown fragment
    |  (appends to .md file with "\n\n" join)
    v
.orca/transcripts/{session_id}.md
    |  (OrcaApp polls mtime every 3s for active sessions)
    v
IssueDetail Markdown widget (auto-scrolls to bottom)
```

### Files Changed

| File | Change |
|---|---|
| `src/orca/orchestrator/transcript.py` | Add `render_incremental(jsonl_path, byte_offset, last_type)` returning `(markdown, new_offset, new_last_type)` |
| `src/orca/orchestrator/session_sync.py` | Add `_SessionRenderState`, update `_sync_entry` for incremental append with chunk joining, file size guard, truncate-on-restart |
| `src/orca/orchestrator/orchestrator.py` | Change sync interval from 180s to 5s |
| `src/orca/tui/messages.py` | Add `active: bool` to `WorkerRunSelected` |
| `src/orca/tui/app.py` | Add transcript poll timer, update `on_worker_run_selected` to pass `active` flag and manage timer lifecycle |
| `src/orca/tui/widgets/issue_detail.py` | Add `refresh_transcript()` method for timer-driven updates, scroll-to-bottom logic |
| `src/orca/tui/widgets/issue_tree.py` | Pass `active` flag when posting `WorkerRunSelected` |

### Edge Cases

- **Truncated JSONL line:** If we read mid-write, the partial line fails `json.loads`. Track offset per-complete-line (not EOF). The incomplete line is re-read next cycle.
- **JSONL file replaced/truncated:** File size < stored offset → reset offset to 0, truncate .md file.
- **Restart with stale .md:** offset=0 with existing .md → truncate .md before re-rendering.
- **Session completes between syncs:** The final sync renders remaining entries. The TUI stops polling when the session is no longer active (on next state update).
- **Large transcripts:** Each sync cycle is O(new entries). The .md file is fully read by the TUI on each refresh (the Textual Markdown widget requires full content), but this is acceptable for typical transcript sizes.

### Testing

- Unit test `render_incremental`: verify it produces the same output as `render_transcript` when called from offset=0, and correct fragments when called incrementally with `last_type` continuity.
- Unit test `_sync_entry` incremental path: mock a JSONL file, sync twice, verify .md has all content with proper `"\n\n"` joining and offset advanced correctly.
- Unit test file size guard: verify offset reset when JSONL file is smaller than offset.
- Update existing `WorkerRunSelected` tests to include `active` parameter.
- TUI test: verify transcript auto-refresh timer starts on active session selection and stops on navigation away.
