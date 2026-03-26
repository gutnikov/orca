# TUI Redesign Design

## Problem

The current TUI is functional but lacks visual polish. Key information is missing or hard to find: no overall progress indication, no visibility into future workflow steps, no structured view of worker results, and failure context requires manual investigation.

## Goals

- Premium, polished feel with clear visual hierarchy
- At-a-glance understanding of run progress, including loops
- Structured result.json visualization for completed workers
- Inline failure context so errors are immediately visible
- Pending workflow steps visible so you know what's coming

## Non-Goals

- Changing the orchestrator or engine (TUI-only changes)
- Multi-session split view or tabs for parallel workers
- Changing keyboard shortcuts (keep existing bindings)

## Design

### 1. Custom Header Bar

Replace Textual's default `Header` with a custom widget showing:

```
  orca │ ● SMEW-1942_ai_team_prd │ Step 3/5 │ Workers 2 │ 14m
```

**Fields:**
- **Branch/run name** (from `branch_name`)
- **Status dot**: green (running), red (has failures), green checkmark (completed)
- **Step N/M**: tracks the **root issue only**. N = number of unique non-terminal states the root issue has visited. M = total non-terminal states in the config. This is an approximation — in looping workflows N can exceed M (show `N/M` capped at M). In decompose workflows, the root issue sits in a waiting state while children work; the header reflects the root's state, not children's.
- **Workers N**: count of currently active workers
- **Failures** (conditional): "1 failed" in red, shown only when `failure_count > 0` on any issue
- **Elapsed time**: since run start (from first session's `started_at`)

The header is a single `Static` widget with a dark background (`#252540`), styled inline.

### 2. Progress Bar in Tree Panel

A thin 3px horizontal bar under each root/parent issue showing overall pipeline progress.

**Segments:** One segment per unique state in the workflow config (from `StateMachineConfig.states`). Terminal states are excluded.

**Colors:**
- Green (`#8bc88b`): state has been successfully completed at least once
- Yellow (`#d4a064`): currently active state
- Red (`#e06070`): state's last run failed (retries exhausted)
- Gray (`#333`): not yet reached

**Loop handling:** The bar tracks unique states, not visits. When a loop sends the issue back to an earlier state, the yellow segment moves backward. Previously-green segments stay green unless the state is now the active one (then it turns yellow).

**Implementation:** A custom `Static` widget rendered with Rich `Text` using block characters (`█`). Placed as the first child after the issue label in the tree. Recomputed on each state update.

### 3. Pending Steps in Tree

Show future workflow steps as dimmed entries below the active/completed worker runs:

```
  ✓ requirements — 9m     ready
  ⠹ write_tests 1m 10s
  ○ build
  ○ validate
```

**Which steps to show:** All non-terminal states from the workflow config that haven't been visited yet by this issue. Shown as `○ state_name` in dark gray (`#444`).

**Visit counting:** When a state is visited more than once (loops), show a `visit N` badge next to the worker run entry:

```
  ✓ state_a — 2m     needs_revision
  ✓ state_b — 3m     needs_rework
  ⠹ state_a 15s      visit 2
```

Each worker run is a separate chronological entry in the tree. The visit badge is a dim bordered label.

### 4. Result Badges in Tree

Completed worker runs show the `outcome` field from their `result.json` as a small colored badge:

```
  ✓ requirements — 9m     ready        ← green badge
  ✗ planning — 1m         failed       ← red badge
  ✓ scoping — 2m          decompose    ← green badge
```

**Badge styling — color classification:**
The badge color is determined by what transition the outcome triggered:
- **Green** (forward/terminal): the outcome led to a state with a higher index in the config, or to a terminal state. Background `#1a3020`.
- **Yellow** (loopback): the outcome led to a state with a lower or equal index (a loop). Background `#302a1a`.
- **Red** (failure): the worker failed (no result.json, non-zero exit). Background `#301a1a`.

This is derived by comparing the issue's state before and after the worker result event in the event log. No manual classification needed — the engine's transition determines the color.

**Data source:** The `outcome` field comes from the `WorkerResultEvent.result` dict stored in the issue's event log. For failed workers, the `WorkerFailedEvent.error` string is shown instead.

### 5. Failure Context in Tree

When a worker fails (retries exhausted), show the error message inline below the failed run:

```
  ✗ write_tests — 3m     failed
    claude exited with non-zero exit code: 1
```

The error text is shown in red (`#e06070`) at a smaller size, indented under the failed run. This uses the `failure_context` field already stored on the issue (from the recent `propagate failure error` commit).

When a retry is in progress after a failure, show it:

```
  ✗ planning — 1m     failed
    result file not found after claude exited
  ⠹ planning 45s      (retry 1)
```

### 6. Session/Result Tabs

The right panel gets two tabs for completed workers: **Session** and **Result**.

**Tab bar:** A row of two tabs above the session content area, styled with a dark background (`#1e1e30`). Active tab has a bottom border accent (`#d4a064`).

**Behavior:**
- **Active worker selected**: Session tab shown, Result tab grayed out (disabled). Live session polling active.
- **Completed worker selected**: Result tab shown by default (auto-selected). User presses `Tab` to switch to Session log.
- **Issue node selected**: No tabs — shows issue detail (title, description, failure info) as today.
- **Insights selected**: No tabs — shows insights markdown as today.

**Result tab content:** Formatted key/value display of the worker's `result.json`:

```
  ✓ write_tests — completed in 7m 30s

  outcome          tests_written
  test_files       tests/e2e/ai-team/chat.spec.ts
                   tests/e2e/ai-team/file-upload.spec.ts
  summary          Created 3 Playwright test spec files...
  reqs_revision    12
```

Keys left-aligned in dim color, values right of them. Lists shown as multiple lines under the key.

**Data source:** The `result.json` content is available from the worker's result event in the issue's event log (`WorkerResultEvent.result`). For the most recent run, the TUI reads from the state directly.

### 7. Footer

Keep existing bindings. Add contextual hint when a completed worker is selected:

```
  q Quit  r Refresh  n Retry           Tab Session/Result  ▲▼ select  j/k scroll
```

The `Tab Session/Result` hint only appears when a completed worker is selected.

## Files to Modify

| File | Change |
|------|--------|
| `src/orca/tui/app.py` | Replace `Header` with custom `OrcaHeader` widget, update compose |
| `src/orca/tui/widgets/issue_tree.py` | Add progress bar, pending steps, result badges, failure context, visit counts |
| `src/orca/tui/widgets/issue_detail.py` | Add result display capability |
| `src/orca/tui/widgets/terminal_view.py` | Add tab bar (Session/Result), result rendering |
| `src/orca/tui/messages.py` | No changes expected |

## New Files

| File | Purpose |
|------|---------|
| `src/orca/tui/widgets/header.py` | Custom `OrcaHeader` widget |

## What Stays Untouched

- Engine (reducer, config, types, dispatch)
- Orchestrator (worker, tmux session, persistence)
- CLI / runner
- Keyboard shortcuts (q, r, n, h/l, j/k, arrow keys)
