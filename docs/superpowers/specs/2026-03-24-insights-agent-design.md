# Insights Agent Design

An observational agent that monitors workflow progress and proactively surfaces errors, patterns, and recommendations. Enabled via `--insights` flag on `orca run`.

## Overview

The insights agent is a sidecar worker that runs periodically inside the orchestrator. It spawns a Claude subprocess via a new `execute_raw()` method on `ClaudeCodeWorker`, bypassing the issue-specific `DispatchWorkerEffect` / `result.json` pipeline. It reads current state and rendered transcripts, then writes observations to `.orca/runs/{branch}/insights.md`. The TUI displays an "Insights" root-level node for viewing the output.

## Architecture

### Worker Execution Path

The existing `ClaudeCodeWorker.execute()` is tightly coupled to `DispatchWorkerEffect`, `result.json` validation, and issue-specific template rendering. The insights agent needs none of that — it receives a pre-rendered prompt and writes markdown, not structured JSON.

**Solution:** Add `execute_raw(prompt: str, workdir: Path, session_log_path: Path, timeout: int | None = None) -> WorkerOutcome` to `ClaudeCodeWorker`:

- Accepts a pre-rendered prompt string (no template rendering)
- Pipes prompt to Claude subprocess stdin (same subprocess flags as `execute()`)
- Streams stdout to session log JSONL file
- Extracts `session_id` from first JSON message (same as `execute()`)
- Does **not** read or validate `result.json` — returns `WorkerSuccess` on exit code 0, `WorkerFailure` on non-zero
- The insights prompt instructs Claude to write directly to the `insights.md` path (passed as a variable in the prompt)

This keeps all subprocess management centralized in `ClaudeCodeWorker` while allowing the insights agent to bypass the issue/result pipeline.

### Orchestrator — Insights Loop

A new `_insights_loop()` coroutine in `Orchestrator`, started alongside `_sync_sessions_loop()` only when `--insights` is enabled. Runs on a fixed 90-second interval.

**Mechanism:**

- `Orchestrator` gets new constructor params: `insights_enabled: bool = False`, `insights_interval: int = 90`
- `_insights_loop()` sleeps for the interval, then calls `_run_insights()`
- `_run_insights()` gathers serialized state (all issues with statuses, event logs, failure counts) and contents of rendered transcript `.md` files from `.orca/transcripts/`
- Renders the insights prompt via Jinja2 with insights-specific context variables
- Calls `ClaudeCodeWorker.execute_raw()` with the rendered prompt
- Working directory: the repo root (`self._repo_root`), since the insights agent is not associated with any issue worktree
- Session log path: `.orca/sessions/insights-{timestamp}.jsonl`
- The prompt instructs Claude to write output to `.orca/runs/{branch}/insights.md`

**Output modes:**

- **Incremental** (while workers are in-flight): the prompt instructs the agent to append a timestamped `## Update <timestamp>` section with bullet-point observations. The agent receives `insights_so_far` (current file contents, truncated to last 3000 lines to bound token cost) to avoid repeating prior observations.
- **Final** (root issue is terminal): one last run with `mode="final"` that produces a structured summary overwriting the file, with sections: `## Summary`, `## Blockers Encountered`, `## Patterns & Observations`, `## Recommendations`.
- The insights loop cancels itself once the final summary is written.

**Session tracking:**

- Insights worker sessions are logged to `.orca/sessions/` like regular workers
- `SessionManifest` entries use `issue_id: "__insights__"` so the TUI can distinguish them

**Concurrency:**

- Only one insights worker runs at a time. If the previous run hasn't finished when the next tick fires, the tick is skipped. Tracked via `_insights_in_flight: bool`.

**Timeout:**

- Default timeout of 120 seconds for the insights worker. If exceeded, the process is killed and the tick is treated as a failure (logged, skipped).

### CLI Flag & Plumbing

**Runner (`runner.py`):**

- Add `--insights` flag to the `run` subcommand argparser
- Pass `insights_enabled=True` through to `Orchestrator` constructor
- `watch` subcommand doesn't need the flag — it reads `insights.md` from disk if it exists
- The `--insights` flag must be passed on each invocation; it is not persisted. Resuming without the flag means no insights loop runs.

**Prompt template:**

- Ship a default insights prompt template as part of the orca package: `src/orca/orchestrator/prompts/insights.md.j2`
- Not configurable via `orca.yml` in v1 — built-in only

### Insights Prompt Template

The Jinja2 template receives:

- `state` — serialized dict of all issues (id, title, state, failure_count, worker_active, event_log, depends_on, decomposed_from)
- `transcripts` — dict mapping session_id to transcript markdown content (truncated to last ~200 lines per transcript to manage token budget)
- `mode` — `"incremental"` or `"final"`
- `insights_so_far` — current contents of `insights.md` (truncated to last 3000 lines)
- `output_path` — absolute path to `.orca/runs/{branch}/insights.md` where Claude should write output

**Token budget management:**

- Transcripts are truncated to the last ~200 lines each, with a global budget cap of ~3000 lines total distributed across active transcripts
- For incremental runs: only include transcripts that changed since the last insights run (track byte offsets similar to `SessionSync`)
- `insights_so_far` truncated to last 3000 lines
- State serialization is compact — included fully

### TUI — Insights Node

**IssueTree (`issue_tree.py`):**

- After adding all root issue nodes, add an "Insights" node at the bottom of the tree if insights data is available
- Node data: `"insights"` (new node type alongside `"issue:{id}"` and `"session:{id}"`)
- Label: `"◆ Insights"` styled in cyan/blue to differentiate from issue nodes
- Under the Insights node: leaf nodes for each insights worker session from the manifest (filtered by `issue_id == "__insights__"`), same format as regular worker run leaves
- Insights node visibility is determined by the presence of `__insights__` entries in `sessions.json` (already available via `StateReader`), not by checking `insights.md` on disk

**Detail panel:**

- When the user selects the Insights node: read and display `.orca/runs/{branch}/insights.md`
- When the user selects an insights session leaf: show the transcript (same as regular sessions)
- New `InsightsSelected` message in `messages.py` to handle the Insights root node selection

**StateReader:**

- No changes needed — `sessions.json` already contains the `__insights__` entries. The TUI checks for their presence to decide whether to show the Insights node.

**OrcaApp:**

- Handle the new `"insights"` node type in `on_tree_node_highlighted()` — read and display `insights.md`
- Handle `InsightsSelected` message to load and render the file

## Error Handling & Edge Cases

- **Worker failures**: Log and continue. Don't retry — wait for next interval tick. Insights is best-effort and must never block the main workflow.
- **Timeout**: Default 120s. If exceeded, kill process, log error, skip tick.
- **Race with shutdown**: Insights worker is included in task cancellation when root issue becomes terminal. After cancellation, the final structured summary runs synchronously in `orchestrator.run()` after the main loop exits but before the method returns, with a 120s timeout to prevent hanging.
- **Empty state**: First run may happen before any workers complete. The prompt handles this gracefully.
- **Resume**: `insights.md` persists on disk. The insights loop reads `insights_so_far` from the existing file. No special recovery logic. The `--insights` flag must be passed again on resume.
- **Watch mode**: TUI reads `insights.md` if it exists. No insights loop runs.

## Testing

**Unit tests:**

- `_run_insights()` builds correct payload (state serialization, transcript gathering, mode selection)
- Concurrency guard — second tick skipped while insights worker is in flight
- Mode switching — incremental while workers active, final when root is terminal
- Transcript truncation logic (per-transcript and global budget)
- `insights_so_far` truncation
- `execute_raw()` returns success on exit 0, failure on non-zero, respects timeout

**Integration tests:**

- Full insights loop with mock `ClaudeCodeWorker` — verify `insights.md` written to correct path
- TUI renders Insights node when `__insights__` sessions exist in manifest
- TUI displays `insights.md` content when Insights node selected
- `--insights` flag plumbed from CLI to orchestrator
- Resume without `--insights` flag does not start insights loop

**No engine tests needed** — insights agent doesn't touch the reducer or engine types.

## Files Changed

| File | Change |
|------|--------|
| `src/orca/orchestrator/worker.py` | Add `execute_raw()` method to `ClaudeCodeWorker` |
| `src/orca/orchestrator/orchestrator.py` | Add `_insights_loop()`, `_run_insights()`, constructor params, final summary in shutdown |
| `src/orca/orchestrator/runner.py` | Add `--insights` CLI flag, plumb to orchestrator |
| `src/orca/orchestrator/template.py` | Add `render_insights_prompt()` for insights-specific Jinja2 context |
| `src/orca/orchestrator/prompts/insights.md.j2` | New insights prompt template |
| `src/orca/tui/widgets/issue_tree.py` | Add Insights root node, insights session leaves |
| `src/orca/tui/widgets/issue_detail.py` | Handle `"insights"` node type |
| `src/orca/tui/app.py` | Handle `"insights"` node in `on_tree_node_highlighted()`, handle `InsightsSelected` |
| `src/orca/tui/messages.py` | Add `InsightsSelected` message |
| `tests/orchestrator/test_insights.py` | New test file |
