# Insights Agent Redesign

## Problem

The current insights agent is a periodic sidecar that runs as short piped subprocess invocations every N minutes. It receives a pre-rendered summary of state and transcripts, writes to `insights.md`, and exits. This approach is:
- **Stateless** — each invocation starts fresh with no memory of previous findings
- **Lossy** — it receives a summary, not the raw data, missing details
- **Different from workers** — uses `execute_raw()` with piped subprocess instead of tmux, making it a separate code path to maintain

## Goals

- Single long-lived tmux session that runs for the entire pipeline
- Agent reads raw files directly (state.json, logs, session logs) — no pre-rendered summaries
- Structured `insights.json` output with findings, detail, and remediation
- Insights shown as tree nodes in TUI, selectable to view detail
- Self-terminating: agent detects pipeline completion and writes final summary
- Uses the same tmux + file-based session log infrastructure as regular workers

## Non-Goals

- Changing the engine or reducer
- Interactive insights (agent is read-only, doesn't modify state or trigger retries)
- Real-time streaming of individual insight entries (TUI polls the file)

## Design

### 1. Insights Agent Lifecycle

The insights agent runs as a single `TmuxSession` for the entire pipeline.

**Spawn:** At pipeline start (in `orchestrator.run()`), if `--insights` is enabled:
1. Create `TmuxSession(session_name="insights-{tracking_id}")`
2. Write the prompt to a file, pipe via `cat prompt | claude --dangerously-skip-permissions --max-turns 200`
3. Register the session for file-based log capture (same `hot_sessions` / `session_log_paths` mechanism)
4. The session log is saved to `.orca/sessions/insights-{timestamp}.log`

**Agent behavior:** The prompt instructs the agent to loop:
1. Read `state.json` to understand current pipeline state
2. Read `sessions.json` to see worker history
3. Read `orca.log.jsonl` for errors
4. Read worker session logs (`.orca/sessions/*.log`) for failure context
5. Investigate problems, write findings to `insights.json`
6. Check if all issues are terminal — if yes, write final summary and exit
7. Sleep for N minutes (default 5), repeat

**Termination:** The agent self-terminates when it detects all issues in `state.json` are in terminal states. On its final cycle, it writes a wrap-up entry to `insights.json`.

**Cleanup:** When the orchestrator's `run()` method exits (pipeline done or error), it does a final scrollback capture and closes the tmux session (same as regular workers).

### 2. insights.json

Located at `.orca/runs/{branch}/insights.json`. The agent creates and appends to this file.

```json
[
  {
    "timestamp": "2026-03-26T10:15:00Z",
    "severity": "error",
    "title": "Worker failed: result file not found",
    "detail": "The requirements worker exited with code 0 but no result.json was written...",
    "remediation": "Update the prompt template to use {{result_path}} directly..."
  },
  {
    "timestamp": "2026-03-26T10:20:00Z",
    "severity": "warning",
    "title": "3 bouncebacks: planning → implementing → planning",
    "detail": "Login flow issue has bounced between planning and implementing 3 times...",
    "remediation": "Consider adding more explicit acceptance criteria in the planning prompt..."
  },
  {
    "timestamp": "2026-03-26T10:45:00Z",
    "severity": "summary",
    "title": "Pipeline completed: 32m, 3/4 issues succeeded",
    "detail": "Total elapsed: 32 minutes. 4 issues created, 3 completed successfully, 1 failed after 3 retries. 12 worker runs total (9 succeeded, 3 failed)...",
    "remediation": "1. Fix result.json path in requirements template (HIGH - caused 2 failures)\n2. Add validation criteria to planning prompt (MEDIUM - caused bouncebacks)\n3. Consider increasing inactivity timeout for implementing state (LOW)"
  }
]
```

**Formatting:** The `detail` and `remediation` fields support markdown. The TUI renders them using Textual's `Markdown` widget when an insight entry is selected.

**Severity levels:**
- `error` — failures, blocked pipeline, deadlocks
- `warning` — bouncebacks, long-running workers, retries
- `info` — observations, successful completions
- `summary` — final wrap-up entry (always last)

### 3. Investigation Targets

The agent's prompt instructs it to check for these on each wake-up:

**Error-level:**
- Worker failed (non-zero exit, missing result.json, timeout)
- Pipeline deadlocked (no workers in-flight, not terminal)
- Orca log contains ERROR-level entries

**Warning-level:**
- More than 2 bouncebacks on same issue (A→B→A→B pattern detected via `visit_counts`)
- Worker retry in progress (`failure_count > 0` with `worker_active`)
- Single worker running >15 minutes without visible progress
- Orca log contains WARNING-level entries

**Info-level:**
- Issue completed successfully
- All child issues finished, parent synthesizing
- Pipeline approaching completion

**Final wrap-up:**
- Total elapsed time
- Issues: created, completed, failed
- Worker runs: total, succeeded, failed, retried
- Ordered remediation list (highest impact first)
- Recommendations for next run

The agent reads raw files for evidence. If it can't determine a root cause, it says so explicitly.

### 3b. Workflow Optimization

Beyond diagnosing runtime problems, the insights agent evaluates whether the workflow design itself is serving the task well. It reads worker session logs (`.orca/sessions/*.log`) to understand what workers actually spend time doing, then proposes concrete changes.

The agent has full latitude to suggest any workflow improvement, including but not limited to:

- **Merging states** — two consecutive states where the second re-reads the first's output
- **Splitting states** — a single state doing too much (>20min, multi-task session logs)
- **Adding states** — missing steps the workers keep doing ad-hoc (e.g., always starts by reading docs)
- **Removing states** — unnecessary steps that add overhead without value
- **Changing transitions** — different outcome routing, better loopback conditions
- **Adjusting parallelism** — decompose differently, change `max_workers`
- **Improving prompts** — session logs reveal workers misunderstanding instructions
- **Tuning settings** — retry counts, timeouts, `max_visits`

**Evidence-based:** The agent forms hypotheses from multiple sources:
- **Session logs** (`.orca/sessions/*.log`) — what workers actually spent time doing, where they got stuck
- **Prompt templates** (paths discovered from `orca.yml` — each state's `worker.prompt` field) — what workers were instructed to do. Comparing instructions vs actual behavior reveals prompt issues (unclear guidance, missing context, conflicting instructions)
- **Timing data** (`sessions.json`) — how long each step took, patterns across runs
- **State data** (`state.json`) — visit counts, failure counts, current pipeline state
- **Orca config** (`orca.yml`) — workflow structure, transition rules, settings

**Output:** Workflow suggestions are `insights.json` entries (typically `warning` or `info` severity). The `remediation` field contains concrete proposed `orca.yml` changes as markdown yaml code blocks:

```json
{
  "severity": "warning",
  "title": "Consider merging requirements and write_tests states",
  "detail": "The write_tests worker spends its first 2 minutes re-reading the requirements output. Session log shows:\n\n> Reading 4 files... tests/e2e/ai-team/e2e-requirements.md\n\nThis is redundant — the requirements worker already produced this content.",
  "remediation": "Merge into a single `plan_and_write_tests` state:\n\n```yaml\nstates:\n  plan_and_write_tests:\n    worker:\n      kind: claude-code\n      prompt: prompts/plan-and-write-tests.md\n    on:\n      tests_written: build\n```\n\nThis eliminates redundant context loading and saves ~2 minutes per run."
}
```

### 4. Prompt Design

New prompt at `src/orca/orchestrator/prompts/insights.md` (not a Jinja2 template — static prompt).

Key sections:
- **Role:** You are a diagnostician monitoring an automated workflow orchestrator
- **Your job:** Find problems worth acting on. If nothing is wrong, say so briefly and sleep.
- **Files to read:** Exact paths to state.json, sessions.json, orca.log.jsonl, and session log directory
- **Output format:** Read and update `.orca/runs/{branch}/insights.json` — append new findings, don't duplicate existing ones
- **Investigation checklist:** The targets listed in Section 3
- **Sleep pattern:** After investigating, wait N minutes before checking again. Use `sleep 300` or equivalent.
- **Termination:** When all issues in state.json have terminal states, write the final summary entry and stop.

The prompt includes the exact file paths (run directory, branch name) baked in at spawn time by the orchestrator.

### 5. TUI Integration

**Tree display:** The Insights node becomes a parent with children:

```
  ◆ Insights
    ⚠ Worker failed: result file not found
    ⚠ 3 bouncebacks: planning → implementing
    ℹ Pipeline completed: 32m, 3/4 succeeded
```

Icons by severity:
- `error`: `●` red
- `warning`: `⚠` yellow
- `info`: `ℹ` dim
- `summary`: `◆` cyan

Selecting the Insights parent node shows the insights session log (the agent's terminal output) in the right panel — same as selecting a worker run.

Selecting an insight child node shows the full detail + remediation in the right panel (rendered as formatted text in IssueDetail or TerminalView).

**Polling:** The TUI reads `insights.json` on the same 1.5s state poll interval. New entries appear as tree children automatically.

### 6. Orchestrator Changes

**Remove:**
- `_run_insights_once()` method
- `_insights_loop()` method
- `execute_raw()` from `ClaudeCodeWorker` (only used by insights)
- `serialize_state_for_insights()`, `render_insights_prompt()`, `truncate_insights_so_far()` from insights.py/template.py
- `insights.md` file creation

**Add to `run()` method:**
```python
if self._insights_worker is not None:
    insights_session = TmuxSession(session_name=f"insights-{uuid4()}", cols=120, rows=40)
    # Write prompt with baked-in paths
    prompt = self._build_insights_prompt(run_dir, branch_name)
    # Spawn in tmux
    await insights_session.spawn("claude", [...], cwd=repo_root, stdin_data=prompt.encode())
    # Register for log capture
    self._tmux_sessions[insights_tracking_id] = insights_session
    self._session_log_paths[insights_tracking_id] = str(insights_log_path)
```

After the main loop exits (pipeline terminal):
- Wait briefly for insights agent to detect completion and write summary
- Final scrollback capture
- Close the tmux session

**Constructor changes:**
- Remove `insights_worker: ClaudeCodeWorker | None` parameter
- Add `insights_enabled: bool = False` (already exists via flag)
- Remove `_insights_interval`, `_insights_timeout` fields

### 7. What Gets Removed

| File | Change |
|------|--------|
| `src/orca/orchestrator/orchestrator.py` | Remove `_run_insights_once`, `_insights_loop`, insights task management |
| `src/orca/orchestrator/worker.py` | Remove `execute_raw()` method |
| `src/orca/orchestrator/insights.py` | Remove `serialize_state_for_insights`, `gather_transcripts` (already dead), `truncate_insights_so_far` |
| `src/orca/orchestrator/template.py` | Remove `render_insights_prompt` |
| `src/orca/orchestrator/runner.py` | Remove `insights_worker` creation, simplify to just pass `insights_enabled` flag |
| `src/orca/tui/widgets/issue_detail.py` | Remove `show_insights()` method |
| `src/orca/orchestrator/prompts/insights.md.j2` | Delete (replaced by static prompt) |

### 8. What Gets Added/Modified

| File | Change |
|------|--------|
| `src/orca/orchestrator/prompts/insights.md` | New static prompt for the long-lived insights agent |
| `src/orca/orchestrator/orchestrator.py` | New insights tmux session spawn + cleanup in `run()` |
| `src/orca/tui/widgets/issue_tree.py` | Read `insights.json`, render entries as Insights children |
| `src/orca/tui/app.py` | Handle insight entry selection, show detail in right panel |
| `src/orca/tui/messages.py` | Add `InsightEntrySelected` message |

## Edge Cases

- **insights.json doesn't exist yet:** Insights node shown with no children. Agent hasn't written first finding yet.
- **insights.json malformed:** TUI ignores parse errors, shows whatever entries parsed successfully.
- **Agent exits early (crash):** Last scrollback captured. Existing insights.json entries preserved. No automatic restart.
- **Pipeline finishes before first wake-up:** Agent detects terminal state on first check, writes summary immediately.
- **No problems found:** Agent writes a single `info` entry: "All systems nominal" and sleeps.

## What Stays Untouched

- Engine (reducer, config, types, dispatch)
- Regular worker execution (TmuxSession, file-based logs)
- `--insights` CLI flag
- Session manifest (sessions.json)
