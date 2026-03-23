# Textual TUI for Orca

## Overview

A terminal-based dashboard for monitoring Orca orchestrator runs, built with [Textual](https://github.com/Textualize/textual). Launched via `orca watch <branch>` as a separate command from `orca run`. The TUI reads persisted state from disk and polls for updates — no coupling to the orchestrator process.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Interaction model | Interactive Viewer | Navigate and inspect, no controls in v1. Controls can be layered later. |
| Integration | Separate command (`orca watch`) | Keeps `orca run` headless-friendly. TUI is a pure reader. |
| Data source | Poll `state.json` every 1.5s | Simple, no IPC needed. 1-2s latency is fine for multi-minute state transitions. |
| Layout proportions | 30% / 40% / 30% | Balanced panels — history gets room for timestamps and outcomes. |
| Tree node content | Title + state badge + worker spinner | Maximum at-a-glance information without clutter. |
| Architecture | Standalone Textual App | New `src/orca/tui/` package. Zero changes to orchestrator. Reuses existing types and persistence. |

## Package Structure

```
src/orca/tui/
├── __init__.py
├── app.py              # OrcaApp — main app, layout, polling timer
├── widgets/
│   ├── __init__.py
│   ├── issue_tree.py   # Left panel — Tree widget with issue hierarchy
│   ├── issue_detail.py # Center panel — Markdown rendering of selected issue
│   └── status_history.py # Right panel — state transition timeline
└── state_reader.py     # Reads & deserializes state.json + orca.yml config
```

## Entry Point

New CLI command: `orca watch <branch-name>`

- Locates `.orca/runs/{branch}/state.json` and `orca.yml` in the repo root
- Loads config once, launches `OrcaApp`
- Added to the existing CLI in `runner.py` (or a new `cli.py` if runner grows too large)

## Dependency

Add `textual >= 1.0` to `pyproject.toml` as an optional dependency (e.g. `[project.optional-dependencies] tui = ["textual>=1.0"]`). The `orca watch` command imports textual lazily and errors with a helpful message if not installed.

## Components

### StateReader (`state_reader.py`)

Thin layer responsible for reading orchestrator state from disk.

- Takes run directory path (`.orca/runs/{branch}/`)
- Reads `state.json`, deserializes into existing `State` dataclass from `orca.engine.types`
- Tracks file mtime — skips re-read when unchanged
- Returns `None` if file doesn't exist yet (run hasn't started)
- Loads `orca.yml` once at startup via existing `parse_config()` from `orca.engine.config`
- No new serialization format — wraps `Persistence.load()` internally, adding mtime checks on top
- Outcome values for the history timeline are extracted from `EventLogEntry.data["outcome"]`

### OrcaApp (`app.py`)

Main Textual application.

- Horizontal layout with three panels using CSS fractions: `3fr / 4fr / 3fr`
- Panels separated by Textual border styling
- Header bar: branch name + run status badge (Running / Completed / Deadlocked)
- Footer: keybinding hints
- `set_interval(1.5)` timer calls `StateReader.read()`
- When state changes, posts `StateUpdated(state)` message to all widgets

**Run status detection** (shown in header):
- **Running**: `state.json` mtime changed within last 10 seconds
- **Completed**: root issue is in a terminal state (checked via config)
- **Deadlocked**: root issue not terminal and file unchanged for 30s+ (heuristic)

### IssueTree (`widgets/issue_tree.py`)

Left panel — hierarchical issue browser.

- Extends Textual's `Tree` widget
- Builds tree from `State.issues` using `decomposed_from` to establish parent-child relationships
- Root issues (no `decomposed_from`) are top-level nodes
- Each node label: `{title} [{state}] {spinner}`
  - Title from `issue.fields["title"]`
  - State badge color-coded (active states green, terminal grey, passive yellow — derived from config)
  - Spinner character `⟳` shown when `issue.worker_active is True`
- On `StateUpdated`: diffs issue set, adds new nodes, updates changed labels, preserves expanded/collapsed state and cursor position
- Selecting a node posts `IssueSelected(issue_id)` message consumed by detail and history panels

### IssueDetail (`widgets/issue_detail.py`)

Center panel — markdown rendering of the selected issue.

- Uses Textual's `Markdown` widget inside a `VerticalScroll` container
- On `IssueSelected`: renders the issue's fields as markdown:
  ```markdown
  # {title}

  {description}
  ```
- If no issue selected, shows placeholder text: "Select an issue from the tree"
- Re-renders on `StateUpdated` if the selected issue's fields changed

### StatusHistory (`widgets/status_history.py`)

Right panel — vertical timeline of state transitions.

- `Static` widget inside a `VerticalScroll` container
- On `IssueSelected`: reads `issue.event_log` entries to reconstruct transition history
- Renders a vertical timeline:
  ```
  ● triage        2m ago
    outcome: ready
        ↓
  ● work          1m ago
    outcome: decompose
        ↓
  ◉ review        now
  ```
- Current state: filled marker `◉`; past states: open marker `●`
- Each entry shows: state name, relative time, and outcome (from the event that caused the transition)
- Re-renders on `StateUpdated` if the selected issue's event log changed

## Keybindings

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate tree |
| `Enter` / `→` | Expand/collapse tree node |
| `r` | Force refresh (re-read state.json immediately) |
| `q` | Quit |

## Data Flow

```
state.json (disk)
      │
      ▼
  StateReader ──(1.5s poll)──► OrcaApp
                                  │
                            StateUpdated message
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
          IssueTree         IssueDetail        StatusHistory
              │
        IssueSelected message
              │
              ├──────────────────►├──────────────────►│
```

## What This Does NOT Include

- **Controls**: No advancing issues, retrying workers, or pausing the orchestrator. Viewer only.
- **Log streaming**: No live log panel. The JSONL log is not surfaced in the TUI.
- **Transcript viewing**: No Claude session transcripts. Those remain as markdown files.
- **Orchestrator changes**: Zero modifications to the engine or orchestrator packages.

These can all be added incrementally in future iterations.
