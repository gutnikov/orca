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
def render_incremental(jsonl_path: Path, byte_offset: int) -> tuple[str, int]:
    """Read new JSONL entries from byte_offset, render to markdown.

    Returns:
        (new_markdown, new_byte_offset) — the rendered text for new entries only,
        and the updated offset to pass on the next call.
    """
```

This reads from `byte_offset` to EOF, parses each new line, renders the entries using the existing `_render_entries` logic, and returns the new markdown fragment plus the updated offset.

The existing `render_transcript` function stays unchanged for one-shot rendering of completed sessions.

**Continuity between chunks:** The existing renderer tracks `last_type` to insert separators between consecutive assistant turns. The incremental renderer must persist this across calls. Add `last_type` to the tracked state alongside `byte_offset`.

### Session Sync Changes

**`SessionSync` gains per-session tracking state:**

```python
@dataclass
class _SessionRenderState:
    byte_offset: int = 0
    last_type: str = ""
```

Stored in-memory on the `SessionSync` instance as `dict[str, _SessionRenderState]` keyed by session_id. No need to persist to disk — on restart, offset=0 triggers a full re-render (same as current behavior).

**`_sync_entry` changes:**

- For active sessions (`completed_at is None`): call `render_incremental` with stored offset, **append** new markdown to the .md file, update stored offset.
- For completed sessions with no .md file: full render via `render_transcript` (existing behavior).
- For completed sessions with an existing .md file: do one final incremental render to capture any trailing entries, then stop syncing this session.

**Append vs overwrite:** Active sessions append to the .md file (`open(target, "a")`). This avoids rewriting the entire file each cycle. The .md file grows incrementally just like the source JSONL.

### Sync Interval

Change `_sync_sessions_loop` interval from 180s to **5s**.

Only active sessions (where `completed_at is None`) need syncing each cycle. Completed sessions that have already been rendered are skipped entirely via the existing `needs_render` check.

At 5s intervals with incremental reads, each sync cycle only processes a few KB of new JSONL data per active session — negligible I/O.

### TUI Auto-Refresh

**`IssueDetail` gains a transcript polling timer:**

When `show_transcript(session_id)` is called for an active session, start a timer (~3s interval) that:
1. Stats the .md file for mtime changes
2. If changed, re-reads the file and updates the Markdown widget
3. Scrolls to the bottom to show the latest content

When the user navigates away (selects a different node), the timer stops.

**Detecting active vs completed:** The `IssueDetail` needs to know if the session is still active. Pass this info from the tree (which has the sessions list) via the `WorkerRunSelected` message — add an `active: bool` field.

**Scroll behavior:** Auto-scroll to bottom only if the user was already at the bottom (within a small threshold). If they've scrolled up to read earlier content, don't jump them.

### Data Flow

```
Claude Code CLI
    |  (appends JSONL entries as work happens)
    v
~/.claude/projects/{hash}/{session_id}.jsonl
    |  (SessionSync reads new bytes every 5s)
    v
render_incremental(path, offset) -> new markdown fragment
    |  (appends to .md file)
    v
.orca/transcripts/{session_id}.md
    |  (TUI polls mtime every 3s for active sessions)
    v
IssueDetail Markdown widget (auto-scrolls to bottom)
```

### Files Changed

| File | Change |
|---|---|
| `src/orca/orchestrator/transcript.py` | Add `render_incremental(jsonl_path, byte_offset, last_type)` |
| `src/orca/orchestrator/session_sync.py` | Add `_SessionRenderState`, update `_sync_entry` for incremental append, track per-session state |
| `src/orca/orchestrator/orchestrator.py` | Change sync interval from 180s to 5s |
| `src/orca/tui/messages.py` | Add `active: bool` to `WorkerRunSelected` |
| `src/orca/tui/widgets/issue_detail.py` | Add transcript polling timer, auto-refresh, scroll-to-bottom logic |
| `src/orca/tui/widgets/issue_tree.py` | Pass `active` flag when posting `WorkerRunSelected` |

### Edge Cases

- **Truncated JSONL line:** If we read mid-write (Claude Code hasn't flushed a complete line), the partial line will fail `json.loads`. Skip it and don't advance the offset past it — it'll be complete on the next cycle.
- **Session completes between syncs:** The final sync renders any remaining entries. The TUI stops polling when it sees the session is no longer active (on next state update).
- **Large transcripts:** Incremental rendering keeps each sync cycle O(new entries) not O(total entries). The .md file grows but is only fully read by the TUI on initial load; subsequent updates append and the TUI re-reads the full file (acceptable since Markdown widget needs the full content).

### Testing

- Unit test `render_incremental`: verify it produces the same output as `render_transcript` when called from offset=0, and correct fragments when called incrementally.
- Unit test `_sync_entry` incremental path: mock a JSONL file, sync twice, verify .md has all content and offset advanced.
- TUI test: verify `IssueDetail` auto-refresh timer starts/stops correctly.
