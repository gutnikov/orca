# Pty-Based Worker Output Design

## Problem

The current transcript pipeline is fragile and tightly coupled to Claude Code's `--output-format stream-json` mode:

1. Workers run `claude --print --output-format stream-json`, producing JSONL
2. JSONL is written to `.orca/sessions/` as session logs
3. The TUI extracts `claude_session_id` from session logs, finds Claude's transcript in `~/.claude/projects/`, and incrementally renders JSONL to markdown
4. Completed sessions are rendered to `.orca/transcripts/*.md` by a background sync loop

This pipeline has several problems:
- **Fragile session ID extraction** — picking the wrong session log causes cross-worker transcript leakage (recently fixed by filtering by state name, but the root issue is architectural)
- **Claude-specific** — the entire pipeline assumes `stream-json` output format, blocking support for other CLI agents (Aider, OpenCode, Codex, etc.)
- **Lossy** — JSONL-to-markdown rendering discards terminal formatting, colors, and interactive elements
- **Laggy** — 1.5s poll interval plus markdown re-rendering adds perceptible delay

## Solution

Replace the JSONL transcript pipeline with direct pty-based worker spawning. Each worker runs in its own pseudo-terminal, and the TUI renders the terminal output directly — the same output the agent would show in a regular terminal session.

### Goals
- **Live terminal output** in the TUI with full ANSI fidelity (colors, cursor, clearing)
- **Agent-agnostic** — any CLI tool that runs in a terminal works
- **Eliminate transcript pipeline** — no more session ID extraction, JSONL parsing, or markdown rendering
- **Frozen scrollback** for completed workers — select a finished worker and scroll through its full output

### Non-Goals
- Interactive input to workers (future consideration, not in scope)
- Replacing the insights worker pipeline (stays piped/markdown)

## Design

### Component 1: PtySession

A new class in `src/orca/orchestrator/pty_session.py` that encapsulates a pty-backed subprocess with an in-memory terminal emulator.

```python
class PtySession:
    screen: pyte.HistoryScreen   # live terminal state + scrollback
    alive: bool                  # process still running
    pid: int

    def __init__(self, cols: int = 120, rows: int = 40) -> None: ...
    async def spawn(self, cmd: str, args: list[str], cwd: Path, env: dict | None = None) -> None: ...
    async def read_loop(self) -> None: ...
    def resize(self, cols: int, rows: int) -> None: ...
    def snapshot(self) -> list[rich.text.Text]: ...
    def close(self) -> None: ...
```

**Pty allocation:**
- `os.openpty()` creates master/slave fd pair
- Terminal size set via `fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack(...))`
- Child process spawned via `subprocess.Popen` with slave fd as stdin/stdout/stderr

**Async read loop:**
- Master fd set to `O_NONBLOCK` via `fcntl`
- Registered with `asyncio.get_event_loop().add_reader()` for event-driven reads (not polled)
- Raw bytes fed to `pyte.Stream` which updates `pyte.HistoryScreen`

**Terminal emulation:**
- `pyte.HistoryScreen` (not plain `Screen`) — maintains scrollback history
- Handles VT100/VTXXX escape sequences: colors, cursor positioning, clearing, scroll regions

**Resize:**
- `resize(cols, rows)` updates `pyte.HistoryScreen` dimensions and sends `TIOCSWINSZ` ioctl to master fd
- This delivers `SIGWINCH` to the child process, which reflows its output

**Snapshot:**
- Converts pyte screen buffer + scrollback history into a list of `rich.text.Text` objects
- Maps pyte character attributes (fg, bg, bold, italic, underline) to Rich styles
- Used to freeze terminal state when worker completes

**Scrollback limits:**
- `pyte.HistoryScreen` accepts a `history` parameter (max scrollback lines). Default to 10,000 lines per session.
- Oldest lines are discarded when the limit is reached (pyte's built-in behavior).
- With multiple concurrent workers, worst case memory is bounded: `num_workers * 10,000 lines * ~200 bytes/line` ~ 20MB for 10 workers.

**Error handling:**
- `os.openpty()` can fail if the system runs out of pty devices. `spawn()` raises a clean error that surfaces as `WorkerFailure`.

**Dependencies:** `pyte` (pure Python, well-maintained VT100 emulator). Note: pyte does not support some modern terminal features (24-bit color, OSC hyperlinks, kitty graphics). These degrade gracefully — unsupported sequences are ignored, which is acceptable for our use case.

### Component 2: TerminalView Widget

A new Textual widget in `src/orca/tui/widgets/terminal_view.py` that replaces the transcript rendering in `IssueDetail`.

**Two rendering modes:**

**Live mode** (active worker selected):
- Holds reference to worker's `PtySession`
- Timer (~50ms) reads `pty_session.screen`, converts to Rich `Text` lines, renders into a `Static` widget
- Scrolling up shows scrollback history from `pyte.HistoryScreen`
- Scrolling back to bottom returns to live screen
- On widget `Resize` event: calls `pty_session.resize(new_cols, new_rows)`

**Frozen mode** (completed worker selected):
- Receives a `FrozenTerminal` (list of `rich.text.Text` lines)
- Renders as scrollable static content
- No timer, no pty reference
- On resize: lines are truncated to current width (not re-wrapped). This matches terminal semantics — the output was originally rendered at a specific width. Some clipping on narrow panels is acceptable for completed sessions.

**Resize propagation:**
- Initial spawn: `PtySession` created with the widget's current content width
- On TUI panel resize: Textual fires `Resize` event, widget calls `pty_session.resize()`
- Agent receives `SIGWINCH` and reflows output

### Component 3: Pty Registries in Orchestrator

Two in-memory registries bridge the orchestrator and TUI:

```python
# In Orchestrator.__init__
self._pty_registry: dict[str, PtySession] = {}       # tracking_id -> live session
self._frozen_registry: dict[str, FrozenTerminal] = {} # tracking_id -> frozen snapshot
```

**Lifecycle:**
1. `_spawn_worker()` creates `PtySession`, stores in `pty_registry[tracking_id]`
2. TUI user selects worker -> looks up `pty_registry[id]` -> live mode
3. Worker completes -> `snapshot()` -> stored in `frozen_registry[id]` -> pty closed, removed from `pty_registry`
4. TUI user selects completed worker -> looks up `frozen_registry[id]` -> frozen mode

**Thread safety:** The orchestrator runs in a daemon thread with its own asyncio event loop, while the TUI runs on the main thread. The registries are shared across threads, so access requires synchronization:
- Both registries are guarded by a single `threading.Lock`.
- The orchestrator acquires the lock when adding/removing entries (infrequent, fast).
- The TUI acquires the lock when looking up a session on selection (infrequent, fast).
- The TUI's 50ms render timer does NOT acquire the lock per-tick — it holds a local reference to the `PtySession` obtained during selection. pyte's `Screen` is read by the TUI timer and written by the orchestrator's `read_loop()`. Since the TUI only reads screen state for display (not for correctness), a momentary inconsistent read is acceptable — it will be corrected on the next tick. No lock needed on the hot path.

**Headless mode (`--headless`):** The `read_loop()` must still drain the master fd in headless mode — if no one reads, the kernel pty buffer (4KB on macOS) fills up and the child process blocks on writes. In headless mode, `read_loop()` runs normally (feeding pyte), but no snapshots are taken on completion and both registries are skipped.

### Component 4: Worker Layer Changes

`ClaudeCodeWorker.execute()` changes:

**Before:**
```
proc = create_subprocess_exec(
    "claude", "--print", "--output-format", "stream-json", "--verbose",
    "--max-turns", "50", "--permission-mode", "bypassPermissions",
    stdin=PIPE, stdout=PIPE, cwd=workdir,
)
# Write prompt to stdin, read JSONL from stdout, extract session_id
```

**After:**
```
session = PtySession(cols=terminal_width, rows=40)
await session.spawn(
    "claude", ["--max-turns", "50", "--permission-mode", "bypassPermissions"],
    cwd=workdir,
)
# Write prompt to pty stdin
# read_loop() runs concurrently, feeding bytes to pyte
# Wait for process exit, read result.json from disk
```

**Prompt delivery:** Claude Code supports `claude -p "prompt"` for non-interactive single-prompt execution that still renders full TUI output to the terminal (unlike `--print` which outputs structured JSON). This is the right mode: the agent runs its full interactive UI in the pty, the user sees the same output they'd see in a terminal, and the process exits when done. The prompt is passed as a CLI argument, not via stdin. If `-p` proves insufficient (e.g., multi-line prompts), we can write the prompt to a temp file and use `claude -p "$(cat /tmp/prompt.txt)"` or pass via stdin with `-p -`.

**What changes:**
- Uses `claude -p "prompt"` instead of `--print --output-format stream-json`
- Subprocess spawned via `PtySession` instead of `asyncio.create_subprocess_exec`
- No JSONL parsing, no `session_id` extraction from stdout
- `PtySession` reference stored in `pty_registry` keyed by tracking ID for TUI access

**What stays the same:**
- `WorkerSuccess` / `WorkerFailure` dataclasses (the `session_id` field becomes always `None` — it was only used for transcript lookup which is being removed; the field is kept for backward compatibility during migration and dropped in Phase 3)
- `result.json` read and validation on disk
- Inactivity timeout (detect no new bytes on master fd instead of stdout readline timeout)


**Insights worker (`execute_raw`):** Stays piped. Insights doesn't need live display — it writes to `insights.md` which the TUI already handles via markdown rendering.

**Agent-agnostic foundation:** A future `AiderWorker` or `OpenCodeWorker` implements the same `Worker` protocol, spawns its CLI via `PtySession`, and writes results to `result.json` per its own prompt instructions.

### Component 5: IssueDetail Split

The current `IssueDetail` widget handles three concerns: issue info, transcripts, and insights. It splits into:

- **`IssueDetail`** — issue title/description + insights markdown display (unchanged)
- **`TerminalView`** — worker terminal output (new, replaces transcript rendering)

The right panel in the TUI switches between these based on tree selection:
- Issue node selected -> `IssueDetail.show_issue()`
- Worker node selected -> `TerminalView` in live or frozen mode
- Insights node selected -> `IssueDetail.show_insights()`

## Migration Plan

Three phases to avoid a big-bang rewrite:

### Phase 1: Add New Components (Additive Only)
- Implement `PtySession` with spawn, read_loop, resize, snapshot
- Implement `TerminalView` widget with live/frozen modes
- Add `pty_registry` and `frozen_registry` to orchestrator
- Wire `TerminalView` into TUI alongside existing `IssueDetail`
- Add `pyte` dependency

### Phase 2: Switch Worker to Pty
- Replace piped subprocess in `ClaudeCodeWorker.execute()` with `PtySession`
- Drop `--print --output-format stream-json` CLI flags
- Adapt inactivity timeout to pty byte detection
- Verify `result.json` protocol works unchanged

### Phase 3: Remove Old Transcript Pipeline
- Delete `transcript.py` (`render_incremental`, `render_transcript`)
- Remove from `issue_detail.py`: `_extract_claude_session_id()`, `_find_jsonl()`, JSONL refresh logic
- Remove from `session_sync.py`: `backfill_claude_session_ids()`, `claude_session_id` field handling
- Remove from `orchestrator.py`: `_sync_sessions_loop()` (60s markdown rendering loop)
- Remove `.orca/transcripts/` directory management
- Clean up `session_sync.py` manifest (no longer needs `claude_session_id`)
- Drop `session_id` field from `WorkerSuccess`/`WorkerFailure` dataclasses
- **Insights worker adaptation:** The insights worker currently calls `gather_transcripts()` to collect rendered `.orca/transcripts/*.md` files as context. With the transcript pipeline removed, insights needs an alternative source. Options: (a) convert frozen `PtySession` snapshots to plain text for insights context, (b) keep a lightweight raw-byte log per worker that insights can read. This is deferred to a follow-up design — insights can continue using stale/missing transcripts gracefully (it already handles the case where transcripts don't exist yet).

## What Stays Untouched

- **Engine** (reducer, config, types, dispatch) — zero changes
- **`result.json` protocol** — agents write structured results to disk
- **Insights worker** (`execute_raw`) — stays piped, renders to `insights.md`
- **`state.json` / `sessions.json` persistence** — unchanged
- **Issue tree widget** — unchanged (still reads sessions from manifest)
- **CLI / runner** — unchanged

## Testing Strategy

- **PtySession unit tests:** Spawn a simple program (`echo`, `python -c "print(...)"`) via PtySession, verify pyte screen contains expected output. Test resize by spawning a program that queries terminal size (`tput cols`). Test snapshot produces correct Rich Text objects.
- **TerminalView widget tests:** Use Textual's `pilot` test framework to verify live mode renders screen content, frozen mode displays stored lines, and resize triggers pty resize.
- **Integration test:** Spawn a mock "worker" script that writes colored output, verify the full pipeline from pty spawn through to TUI rendering.
- **Existing engine tests:** Unchanged — engine has no knowledge of the transport layer.

## Session Log Persistence

The current `.orca/sessions/{state}-{timestamp}.jsonl` files are no longer produced in pty mode. For debugging purposes, `PtySession.read_loop()` optionally writes raw bytes to a log file at `.orca/sessions/{state}-{timestamp}.raw`. This is a binary file of the raw pty output (including ANSI escapes) that can be replayed with `cat` for post-mortem debugging. This is opt-in via a `log_path` parameter on `PtySession.spawn()`.

## Estimated Impact

- ~400 lines of transcript code removed
- ~300 lines of pty/terminal code added
- Net simplification: one code path (bytes to screen) replaces four (JSONL to session ID to Claude project lookup to incremental markdown)
- New dependency: `pyte` (pure Python, BSD license)
