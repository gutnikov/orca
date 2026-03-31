# Daemon + MCP + Detachable TUI Design

## Summary

Transform orca from a foreground CLI into a per-repo background daemon that exposes an MCP interface for both agents and humans, with a TUI that attaches/detaches on demand.

## Motivation

Today, orca runs as a foreground process — you launch it, optionally watch the TUI, and it dies when you close the terminal. This limits its usefulness:

- AI agents (Claude Code, etc.) can't programmatically start or inspect orca runs
- You can't walk away and reconnect later
- No way to manage multiple runs from a single view
- No standard integration surface for editors or external tools

A daemon architecture with MCP solves all of these. The daemon runs workflows in the background, MCP provides a universal tool interface, and the TUI becomes a detachable client.

## Architecture

### Approach

Daemon wraps Orchestrator instances. The existing `Orchestrator` class stays mostly unchanged — the daemon is a new layer that hosts multiple Orchestrators in a single async process and exposes them over HTTP on a Unix domain socket.

```
┌─ daemon process ──────────────────────────┐
│  HTTP server (UDS: .orca/daemon.sock)     │
│  ├─ MCP tools handler                     │
│  ├─ TUI API handler                       │
│  │                                        │
│  ├─ Orchestrator (run-1)                  │
│  ├─ Orchestrator (run-2)                  │
│  └─ Orchestrator (run-3)                  │
└───────────────────────────────────────────┘
    ↑ UDS          ↑ UDS           ↑ UDS
 orca mcp       orca tui        orca run
 (stdio shim)   (Textual)      (submit+exit)
```

### Why this approach

- Minimal refactor: Orchestrator is well-tested and stays intact
- Direct in-process access to state (no extra IPC for reads)
- Single event loop manages all runs
- Per-repo scope means concurrent run count is naturally bounded

### Why not alternatives

- **Daemon as supervisor (Orchestrators as child processes):** Process isolation is overkill for per-repo scope. Adds significant IPC complexity for little benefit.
- **Daemon replaces Orchestrator loop:** Cleanest long-term but high-risk refactor. The Orchestrator is tightly coupled to single-run assumptions. Can evolve here incrementally.

## Daemon Process

### Lifecycle

```
orca daemon start
  → Daemonize (double-fork)
  → Write PID to .orca/daemon.pid
  → Bind .orca/daemon.sock
  → Start HTTP server (uvicorn on UDS)
  → Scan .orca/runs/ for resumable state (mark as "interrupted", don't auto-resume)
  → Main event loop: serve requests, manage orchestrators

orca daemon stop
  → Read .orca/daemon.pid
  → Send SIGTERM
  → Daemon: stop accepting new runs
  → Wait for in-flight workers (with timeout)
  → Kill remaining worker subprocesses
  → Cleanup socket and pidfile
```

### Run identity

Each run gets an ID of the form `{branch}:{workflow_name}` (e.g., `feat/auth:orca`). This matches the existing `.orca/runs/{branch}/{workflow}/` directory structure and is the key used in MCP tools, TUI, and log paths. The branch component uses the full ref name with slashes preserved.

### State persistence

No change to `.orca/runs/{branch}/{workflow}/` structure. The daemon's `RunManager` holds live Orchestrator references in memory. Persistence works as today for crash recovery.

### Daemon detection

- All `orca` commands find the repo root via `git rev-parse --show-toplevel`
- `.orca/daemon.sock` lives at repo root
- One daemon per repo, enforced by pidfile
- `orca daemon start` when already running → error with "daemon already running (PID: ...)"
- Stale socket detected by connection attempt; if refused, `orca daemon start` cleans up old socket/pidfile

## MCP Interface

### Transport

MCP streamable HTTP transport served on the UDS. External clients connect through a stdio shim:

```json
{
  "mcpServers": {
    "orca": {
      "command": "orca",
      "args": ["mcp"]
    }
  }
}
```

`orca mcp` reads `.orca/daemon.sock` from the current repo root, checks the daemon is running, and bridges stdio to HTTP over UDS.

### Tools

| Tool | Args | Returns |
|------|------|---------|
| `orca_daemon_status` | — | uptime, active run count, resource usage |
| `orca_start_run` | `task_file`, `workflow?`, `branch?` | `run_id`, initial status |
| `orca_list_runs` | — | list of `{run_id, workflow, branch, status, issue_count, created_at}` |
| `orca_get_run` | `run_id` | full state: issues tree, phases, progress summary |
| `orca_get_issue` | `run_id`, `issue_id` | issue fields, state, event log, children |
| `orca_get_insights` | `run_id` | current insights agent summary text |
| `orca_get_worker_log` | `run_id`, `issue_id`, `tail?` | last N lines (default 100) of worker session scrollback |
| `orca_retry_issue` | `run_id`, `issue_id` | confirmation + new status |
| `orca_stop_run` | `run_id` | confirmation, graceful shutdown initiated |

### Implementation

Each MCP tool handler resolves `run_id` → `Orchestrator` via `RunManager`, then reads state or triggers action. State reads are direct in-memory access. Mutations (retry, stop) are serialized through `RunManager` on asyncio's single-threaded event loop.

### Error handling

- Unknown `run_id` → MCP error with available run IDs
- Daemon not running → `orca mcp` exits with "run `orca daemon start` first"
- Invalid args → MCP error response with description

## TUI Refactor

### New architecture

The TUI becomes a standalone client that connects to the daemon over HTTP/UDS, replacing the current filesystem-polling model.

```
orca tui
  → Connect to .orca/daemon.sock
  → Fetch all runs
  → Display run list view
  → On run selected: drill into existing detail view
  → Poll daemon at ~200ms for state updates
```

### Two-level navigation

1. **Run list view** (new) — table of all runs with status, branch, workflow, issue count, elapsed time. Keybinds to select, stop, retry.
2. **Run detail view** (existing) — IssueTree + IssueDetail + TerminalView + PhasesPanel, mostly unchanged.

### Changes from today

- `StateReader` switches from reading `state.json` on disk to HTTP requests against the daemon. The daemon returns a version counter for cheap change detection.
- `OrcaApp` gains a new top-level screen for the run list.
- `TerminalView` fetches scrollback from the daemon instead of reading log files directly.
- Hot session tracking: TUI tells the daemon which sessions it's viewing (HTTP POST), daemon increases capture frequency for those sessions.

### What stays the same

- All existing widgets (IssueTree, IssueDetail, PhasesPanel, StatusHistory, InsightsModal)
- Keybindings and navigation within a run
- Visual layout and styling

### Without daemon

`orca tui` errors with "daemon not running, run `orca daemon start`".

## CLI Commands

### New command structure

```
orca daemon start              # start daemon for current repo
orca daemon stop               # graceful shutdown
orca daemon status             # health check, active runs

orca run <task.md> [-w workflow] [-b branch] [--base ref]
                               # submit run to daemon, print run_id, exit

orca tui                       # attach TUI to daemon

orca mcp                       # stdio shim for MCP clients

orca runs                      # list runs (table, no TUI)
orca logs <run_id> [issue_id] [--tail N]
                               # print worker log to stdout
```

### Migration

The current `orca <task.md>` entrypoint is removed. The new flow is always daemon-mediated. For the old "start and watch" UX: `orca run <task.md> && orca tui`.

### Implementation

Replace current argparse in `runner.py` with subcommand dispatch in a new `cli/` module. Each subcommand is a thin function that connects to the daemon over UDS.

## Internal Boundaries & Refactoring

### Orchestrator changes

The `Orchestrator` class stays mostly intact but loses startup concerns:

- `runner.py`'s `run()` function currently handles config resolution, persistence setup, branch detection, resume prompting, Slack MCP spawning, and Orchestrator construction. This logic moves to `daemon/manager.py`'s `RunManager`.
- `Orchestrator.__init__()` and `Orchestrator.run()` stay as-is.
- TUI retry mechanism (signal files in `retry/` dir) replaced with direct method call: `RunManager.retry_issue(run_id, issue_id)`.

### New interfaces on Orchestrator / RunManager

- `get_state() → State` — expose existing state
- `get_session_log(issue_id, tail) → str` — read from session capture buffer
- `get_insights() → str` — read from insights state dict
- `stop()` — graceful shutdown: cancel pending, wait for in-flight, mark interrupted
- `hot_session(session_id)` / `cold_session(session_id)` — capture rate signaling

### Engine layer

No changes. Reducer, config, types, dispatch are pure and untouched.

### Module structure

```
src/orca/
  engine/          # unchanged
  orchestrator/    # minor: remove TUI coupling, expose state accessors
  daemon/          # new: server, manager, lifecycle, mcp_tools
  tui/             # refactored: connect to daemon instead of filesystem
  mcp_servers/     # unchanged (slack_hitl stays internal to daemon)
  cli/             # new: subcommand dispatch (replaces runner.py entrypoint)
```

## Error Handling & Edge Cases

### Daemon crashes

- On restart, `orca daemon start` scans `.orca/runs/` for non-terminal runs. These show as "interrupted" in `orca runs`.
- No auto-resume. User explicitly re-submits with `orca run` (detects existing state, offers resume like today).
- Stale socket: `orca daemon start` attempts connect, if refused, cleans up old socket/pidfile.

### Concurrent access

- Multiple TUI/MCP clients connect simultaneously — read-heavy, no contention.
- Mutations serialized through `RunManager` on asyncio's single-threaded event loop. No locking needed.

### Worker subprocess orphans

- Workers run in tmux sessions. If daemon dies, tmux sessions survive.
- On daemon restart, `RunManager` detects orphaned tmux sessions by naming convention.
- `orca daemon stop` sends SIGTERM to all worker subprocesses before exiting.

### Multiple daemons

One per repo, enforced by pidfile. `orca daemon start` in a repo with a running daemon → error.

## Testing Strategy

- **Daemon lifecycle:** Integration tests for start/stop, pidfile, socket cleanup, stale detection.
- **MCP tools:** Unit tests with a mock `RunManager` — verify tool handlers return correct shapes.
- **TUI client:** Test `StateReader` against a mock HTTP server returning state JSON.
- **End-to-end:** Start daemon, submit run via `orca run`, query via MCP tools, verify state transitions.
- **Engine:** No new tests needed — unchanged.

## Dependencies

No new dependencies required:
- `uvicorn` (existing) — supports UDS binding
- `starlette` (existing) — HTTP routing
- `mcp` (existing) — MCP protocol implementation
- `textual` (existing) — TUI framework
- `aiohttp` (existing) — HTTP client for TUI→daemon communication
