# TUI Phases Panel & Insights Modal

## Goal

Redesign the TUI left panel to split into two halves — issue tree on top, full scrollable phase history on bottom — and move insights into a keyboard-triggered modal. This removes the 5-session truncation limit and cleanly separates issue hierarchy from worker execution history.

## Current State

The TUI has two columns:
- **Left:** `IssueTree` (Textual `Tree` widget) showing issues with worker runs and pending steps as child nodes, truncated to last 5 sessions
- **Right:** `IssueDetail` (markdown) or `TerminalView` (session log with Session/Result tabs), toggled by selection

Problems:
- Worker history truncated at 5 sessions — can't see or select older runs
- Tree mixes issue hierarchy, worker runs, and insights into one widget
- Tree gets long and cluttered with many phases

## Design

### Layout

```
┌─────────────────────────────────────────────────────┐
│  OrcaHeader (existing, unchanged)                   │
├──────────────┬──────────────────────────────────────┤
│  Issues      │                                      │
│              │  Session / Result tabs                │
│  • ai-team   │                                      │
│              │  (TerminalView — unchanged)           │
├──────────────┤                                      │
│  Phases      │                                      │
│              │                                      │
│  ⠹ implement │                                      │
│    ↑         │                                      │
│  ✓ build_dep │                                      │
│    ↑         │                                      │
│  ✓ fix_issue │                                      │
│    ↑         │                                      │
│  ✓ build_dep │                                      │
│    ↑         │                                      │
│  ✓ gen_specs │                                      │
│    ↑         │                                      │
│  ✓ gen_prd   │                                      │
├──────────────┴──────────────────────────────────────┤
│  Footer (existing, unchanged)                       │
└─────────────────────────────────────────────────────┘
```

### Left Column: Split Vertically

The existing `IssueTree` area splits into two independent widgets stacked vertically inside a `Vertical` container.

**Top: Issue Tree (simplified)**
- Shows only issue nodes with progress bars — no worker run children, no pending steps, no insights
- Selecting an issue populates the phases panel below
- Same `Tree` widget, just stripped of session/pending leaf nodes

**Bottom: Phases Panel (new widget: `PhasesPanel`)**
- Scrollable list of worker runs for the currently selected issue
- Reversed order: active/current phase on top, oldest at bottom
- `↑` arrows between entries to show execution flow
- No future/pending phases — only active + completed
- Each entry is two lines:
  - Line 1: status icon + worker state name
  - Line 2: elapsed duration (dimmed)
- Active phase: braille spinner (⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏), highlighted background
- Completed phase: green `✓`, no background
- Failed phase: red `✗`
- No truncation limit — all sessions shown, panel scrolls
- Selecting a phase loads its session log in the right panel (same as current worker run selection behavior)

### Insights Modal (new widget: `InsightsModal`)

Insights move from the tree into a modal overlay triggered by the `i` key.

- Full-screen overlay with dimmed background
- Title: "◆ Insights"
- Lists all insight entries with severity icons (● error, ⚠ warning, ℹ info, ◆ summary)
- Navigate with `j/k`, press `Enter` to view detail (shows in right panel behind modal, modal closes), `Esc` to dismiss
- Press `s` to jump to the live insights session log
- Modal reads from the same insights data the tree currently uses

### Keyboard Navigation

| Key | Action |
|-----|--------|
| `h` | Focus issue tree (top-left) |
| `l` | Focus right panel (session/result) |
| `j/k` | Scroll within focused panel |
| `Enter` | Select issue (updates phases) or select phase (loads session) |
| `t` | Toggle Session/Result tabs |
| `i` | Open insights modal |
| `Esc` | Close insights modal |
| `n` | Retry failed issue |
| `q` | Quit |

Focus cycles between three panels: issue tree → phases panel → right panel. `h`/`l` move left/right. When phases panel is focused, `j/k` scroll phases and `Enter` selects.

### Messages / Events

- `IssueSelected` — existing message, now also triggers phases panel update
- `PhaseSelected` — new message from `PhasesPanel`, carries `session_id` and `issue_id`. App handles it the same way as `WorkerRunSelected`
- `InsightsModal` open/close — app toggles the modal overlay widget

### Data Flow

1. User selects issue in tree → `IssueSelected` posted
2. App receives `IssueSelected` → tells `PhasesPanel` to show phases for that issue
3. `PhasesPanel` reads `sessions` list (filtered by `issue_id`) and `issue.event_log` — builds reversed phase list with all sessions (no truncation)
4. User selects a phase → `PhaseSelected` posted with `session_id`
5. App receives `PhaseSelected` → loads session log in `TerminalView` (same path as existing `WorkerRunSelected`)

### State Updates

On each state poll tick (1.5s):
- Issue tree updates as before (minus session children and insights)
- Phases panel refreshes if showing the same issue (updates active spinner, adds new completed phases)
- Insights modal refreshes if open

### CSS Layout

```css
#left-column {
    width: 1fr;
    min-width: 30;
    max-width: 60;
}
#issue-tree {
    height: 1fr;
    min-height: 5;
}
#phases-panel {
    height: 1fr;
    min-height: 10;
    border-top: solid #333;
}
```

Both panels get `1fr` height (50/50 split). The issue tree may grow when there are decomposed child issues; the phases panel scrolls independently.

## Files to Create/Modify

- **Create:** `src/orca/tui/widgets/phases_panel.py` — new `PhasesPanel` widget
- **Create:** `src/orca/tui/widgets/insights_modal.py` — new `InsightsModal` widget
- **Modify:** `src/orca/tui/widgets/issue_tree.py` — remove session children, pending steps, and insights from tree
- **Modify:** `src/orca/tui/app.py` — new layout with `Vertical` split, wire up `PhasesPanel` and `InsightsModal`, add `i` keybinding
- **Modify:** `src/orca/tui/messages.py` — add `PhaseSelected` message
- **Create:** `tests/tui/test_phases_panel.py`
- **Create:** `tests/tui/test_insights_modal.py`
- **Modify:** `tests/tui/test_issue_tree.py` — update for simplified tree (no session children)

## Out of Scope

- Decomposed child issue display (tree already handles this, unchanged)
- Modifying the right panel (TerminalView/IssueDetail) — unchanged
- Header/footer — unchanged
- Changing the orchestrator or engine — TUI-only change
