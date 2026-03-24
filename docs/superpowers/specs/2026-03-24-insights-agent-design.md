# Insights Agent Design

An observational agent that monitors workflow progress and proactively surfaces errors, patterns, and recommendations. Enabled via `--insights` flag on `orca run`.

## Overview

The insights agent is a sidecar worker that runs periodically inside the orchestrator. It reuses the existing `ClaudeCodeWorker` to spawn a Claude subprocess with a dedicated prompt template. It reads current state and rendered transcripts, then writes observations to `.orca/runs/{branch}/insights.md`. The TUI displays an "Insights" root-level node for viewing the output.

## Architecture

### Orchestrator — Insights Loop

A new `_insights_loop()` coroutine in `Orchestrator`, started alongside `_sync_sessions_loop()` only when `--insights` is enabled. Runs on a fixed 90-second interval.

**Mechanism:**

- `Orchestrator` gets new constructor params: `insights_enabled: bool = False`, `insights_interval: int = 90`
- `_insights_loop()` sleeps for the interval, then calls `_run_insights()`
- `_run_insights()` gathers serialized state (all issues with statuses, event logs, failure counts) and contents of rendered transcript `.md` files from `.orca/transcripts/`
- Renders an insights prompt template via Jinja2 and passes it to `ClaudeCodeWorker.execute()`
- The worker writes output to `.orca/runs/{branch}/insights.md`

**Output modes:**

- **Incremental** (while workers are in-flight): the prompt instructs the agent to append a timestamped `## Update <timestamp>` section with bullet-point observations. The agent receives `insights_so_far` (current file contents) to avoid repeating prior observations.
- **Final** (root issue is terminal): one last run with `mode="final"` that produces a structured summary overwriting the file, with sections: `## Summary`, `## Blockers Encountered`, `## Patterns & Observations`, `## Recommendations`.
- The insights loop cancels itself once the final summary is written.

**Session tracking:**

- Insights worker sessions are logged to `.orca/sessions/` like regular workers
- `SessionManifest` entries use `issue_id: "__insights__"` so the TUI can distinguish them

**Concurrency:**

- Only one insights worker runs at a time. If the previous run hasn't finished when the next tick fires, the tick is skipped. Tracked via `_insights_in_flight: bool`.

### CLI Flag & Plumbing

**Runner (`runner.py`):**

- Add `--insights` flag to the `run` subcommand argparser
- Pass `insights_enabled=True` through to `Orchestrator` constructor
- `watch` subcommand doesn't need the flag — it reads `insights.md` from disk if it exists

**Prompt template:**

- Ship a default insights prompt template as part of the orca package: `src/orca/orchestrator/prompts/insights.md.j2`
- Not configurable via `orca.yml` in v1 — built-in only

### Insights Prompt Template

The Jinja2 template receives:

- `state` — serialized dict of all issues (id, title, state, failure_count, worker_active, event_log, depends_on, decomposed_from)
- `transcripts` — dict mapping session_id to transcript markdown content (truncated to last ~200 lines per transcript to manage token budget)
- `mode` — `"incremental"` or `"final"`
- `insights_so_far` — current contents of `insights.md`

**Token budget management:**

- Transcripts are truncated to the last ~200 lines each
- For incremental runs: only include transcripts that changed since the last insights run (track byte offsets similar to `SessionSync`)
- State serialization is compact — included fully

### TUI — Insights Node

**IssueTree (`issue_tree.py`):**

- After adding all root issue nodes, add an "Insights" node at the bottom of the tree if `insights.md` exists on disk
- Node data: `"insights"` (new node type alongside `"issue:{id}"` and `"session:{id}"`)
- Label: `"◆ Insights"` styled in cyan/blue to differentiate from issue nodes
- Under the Insights node: leaf nodes for each insights worker session from the manifest (filtered by `issue_id == "__insights__"`), same format as regular worker run leaves

**Detail panel:**

- When the user selects the Insights node: read and display `.orca/runs/{branch}/insights.md`
- When the user selects an insights session leaf: show the transcript (same as regular sessions)

**No StateReader changes needed** — the TUI already polls `state.json` and `sessions.json`. The insights node is derived from existence of `insights.md` on disk and `sessions.json` entries with `issue_id == "__insights__"`.

## Error Handling & Edge Cases

- **Worker failures**: Log and continue. Don't retry — wait for next interval tick. Insights is best-effort and must never block the main workflow.
- **Race with shutdown**: Insights worker is included in task cancellation when root issue becomes terminal. After cancellation, run the final structured summary synchronously before orchestrator exits.
- **Empty state**: First run may happen before any workers complete. The prompt handles this gracefully.
- **Resume**: `insights.md` persists on disk. The insights loop reads `insights_so_far` from the existing file. No special recovery logic.
- **Watch mode**: TUI reads `insights.md` if it exists. No insights loop runs.

## Testing

**Unit tests:**

- `_run_insights()` builds correct payload (state serialization, transcript gathering, mode selection)
- Concurrency guard — second tick skipped while insights worker is in flight
- Mode switching — incremental while workers active, final when root is terminal
- Transcript truncation logic

**Integration tests:**

- Full insights loop with mock `ClaudeCodeWorker` — verify `insights.md` written to correct path
- TUI renders Insights node and displays content when selected
- `--insights` flag plumbed from CLI to orchestrator

**No engine tests needed** — insights agent doesn't touch the reducer or engine types.

## Files Changed

| File | Change |
|------|--------|
| `src/orca/orchestrator/orchestrator.py` | Add `_insights_loop()`, `_run_insights()`, constructor params |
| `src/orca/orchestrator/runner.py` | Add `--insights` CLI flag, plumb to orchestrator |
| `src/orca/orchestrator/prompts/insights.md.j2` | New insights prompt template |
| `src/orca/tui/widgets/issue_tree.py` | Add Insights root node, insights session leaves |
| `src/orca/tui/widgets/issue_detail.py` | Handle `"insights"` node type |
| `src/orca/tui/app.py` | Handle `"insights"` node in `on_tree_node_highlighted()` |
| `src/orca/tui/messages.py` | Add `InsightsSelected` message if needed |
| `tests/orchestrator/test_insights.py` | New test file |
