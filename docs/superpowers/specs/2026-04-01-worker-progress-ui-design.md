# Worker Progress UI Design

## Summary

Add progress reporting (0–100%) and status text to workers, displayed in the TUI's PhasesPanel and exposed via MCP. Workers optionally report `progress` and `status` during execution; the UI renders these as a thin box-drawing bar (`━`) with a bold percentage.

## Data Model

Two new optional fields per worker session:

| Field      | Type          | Description                                      |
|------------|---------------|--------------------------------------------------|
| `progress` | `int \| None` | 0–100, or `None` if worker hasn't reported yet   |
| `status`   | `str \| None` | Freeform text, e.g. "Exploring sidebar components..." |

These fields are stored on the session dict alongside existing fields (`session_id`, `state`, `started_at`, `completed_at`, `failed`, `interrupted`, `log_path`).

## TUI Rendering Rules

The progress bar uses `━` (U+2501, box-drawing heavy horizontal) characters. Bar width adapts to the available panel width. Percentage is bold, right of the bar, in the worker's accent color.

### Active worker — has progress

```
→ ⡇ field_observer
  Exploring sidebar components...
  ━━━━━━━━━━━━━━━━━━━━━━━━ 68%
  12m 48s
```

- Spinner + worker name in yellow (existing behavior)
- Status text on line 2 (dim)
- Bar on line 3: filled portion in yellow, unfilled in dark gray, bold percentage in yellow
- Elapsed time on line 4 (dim, existing behavior)

### Active worker — no progress yet

```
→ ⡇ field_observer
  12m 48s
```

- Same as current behavior — no bar, no status text
- Bar appears on the first non-zero progress report
- If status text is provided but progress is `None` or 0, show only the status text (no bar)

### Completed worker

```
✓ build_and_run  done
  ━━━━━━━━━━━━━━━━━━━━━━━━ 100%
  5m 50s
```

- Full bar at 100% in dim/gray style
- If the worker never reported progress, no bar is shown (same as today)

### Failed worker — had progress

```
✗ generate_prd  stopped
  ━━━━━━━━━━━━━━━━━━━━━━━━ 42%
  4m 35s
```

- Bar frozen at last reported percentage, colored red
- Percentage bold and red

### Failed worker — no progress

```
✗ generate_prd  stopped
  9s
```

- No bar shown — same as today's behavior

### Interrupted worker

Same rules as failed: show frozen bar in orange if progress was reported, otherwise no bar.

## Bar Rendering Details

- **Characters**: `━` (U+2501) for both filled and unfilled segments
- **Filled color**: worker accent color (yellow for active, green for completed, red for failed, orange for interrupted)
- **Unfilled color**: dark gray (#333333 or `dim`)
- **Width**: calculated as `panel_width - indent - percentage_label_width`, targeting ~20–24 characters at typical panel widths
- **Percentage label**: bold, same color as filled bar, separated by one space after the bar

## Implementation Scope

### PhasesPanel changes (`src/orca/tui/widgets/phases_panel.py`)

The `_render_phases` method gains a helper to render the progress bar line. For each session:

1. Read `progress` and `status` from the session dict
2. If active and `progress` is not None and > 0: render status text + bar + percentage
3. If active and `progress` is None or 0 but `status` is set: render only status text
4. If completed and progress was ever reported: render dim full bar at 100%
5. If failed/interrupted and progress was reported: render frozen bar in red/orange

### Session data flow

Sessions already flow as dicts from `StateReader`/`DaemonStateReader` into `PhasesPanel.show_phases()`. The new `progress` and `status` fields are simply additional keys on these dicts — no structural changes needed.

### MCP exposure

`orca_get_run` already returns session data. Adding `progress` and `status` to the session dicts automatically exposes them via MCP. No new MCP tools needed.

### What this spec does NOT cover

- How workers report progress (the worker protocol/engine changes) — that's a separate spec
- Progress persistence to disk — sessions already persist; the new fields follow the same path
- Progress aggregation across multiple workers for a single issue
