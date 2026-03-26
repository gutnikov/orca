# Insights Agent Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the periodic piped-subprocess insights agent with a single long-lived tmux session that reads raw files, writes structured `insights.json`, and integrates with the TUI as tree children.

**Architecture:** The insights agent runs as a `TmuxSession` (same as workers), spawned at pipeline start. The orchestrator registers it for file-based log capture. The agent's prompt instructs it to loop: read state/logs, investigate, write findings to `insights.json`, sleep, repeat. The TUI reads `insights.json` and renders entries as children of the Insights tree node.

**Tech Stack:** Python 3.12, Textual, Rich, TmuxSession (existing)

**Spec:** `docs/superpowers/specs/2026-03-26-insights-redesign-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/orca/orchestrator/prompts/insights.md` | Static prompt for the long-lived insights agent |

### Modified Files
| File | Change |
|------|--------|
| `src/orca/orchestrator/orchestrator.py` | Remove old insights methods, add tmux-based insights spawn/cleanup |
| `src/orca/orchestrator/worker.py` | Remove `execute_raw()` method |
| `src/orca/orchestrator/runner.py` | Remove `insights_worker` creation, pass `insights_enabled` bool |
| `src/orca/tui/widgets/issue_tree.py` | Read `insights.json`, render entries as Insights children |
| `src/orca/tui/app.py` | Handle insight entry selection, show markdown detail |
| `src/orca/tui/messages.py` | Add `InsightEntrySelected` message |
| `src/orca/tui/widgets/issue_detail.py` | Remove `show_insights()`, add `show_insight_entry()` |

### Deleted Files
| File | Reason |
|------|--------|
| `src/orca/orchestrator/prompts/insights.md.j2` | Replaced by static prompt |
| `src/orca/orchestrator/insights.py` | Functions no longer needed (agent reads files directly) |

---

### Task 1: Write the insights prompt

**Files:**
- Create: `src/orca/orchestrator/prompts/insights.md`
- Delete: `src/orca/orchestrator/prompts/insights.md.j2`

This is the core of the redesign — the prompt that drives the long-lived agent.

- [ ] **Step 1: Write the static prompt**

The prompt is NOT a Jinja2 template. It contains placeholders like `{run_dir}`, `{branch_name}`, `{config_path}` that the orchestrator string-formats at spawn time.

Key sections the prompt must include:

**Role & mission:**
- You are a diagnostician monitoring an automated workflow orchestrator called orca
- Your job: find problems worth acting on, propose workflow improvements
- You run for the entire pipeline lifetime, waking up periodically

**Files to read (with exact paths):**
- `{run_dir}/state.json` — current pipeline state (issues, states, visit_counts, failure_counts, event_log)
- `{run_dir}/sessions.json` — worker session history (started_at, completed_at, state, worktree_path)
- `{run_dir}/orca.log.jsonl` — structured orchestrator logs
- `{run_dir}/../../../.orca/sessions/*.log` — worker session terminal logs (tmux scrollback)
- `{config_path}` — orca.yml workflow config (states, transitions, worker prompts)
- Worker prompt files (discover paths from orca.yml `worker.prompt` fields)

**Output format:**
- Read `{run_dir}/insights.json` if it exists
- Append new findings as JSON entries: `{{"timestamp": "...", "severity": "...", "title": "...", "detail": "...", "remediation": "..."}}`
- Severity: error, warning, info, summary
- `detail` and `remediation` support markdown
- Don't duplicate existing entries — check titles before adding
- The file must always be valid JSON (a list of objects)

**Investigation checklist (each wake-up):**

Error-level:
- Worker failed (non-zero exit, missing result.json, timeout) — read session logs for root cause
- Pipeline deadlocked (no workers in-flight, not terminal)
- Orca log contains ERROR-level entries

Warning-level:
- More than 2 bouncebacks (A→B→A→B pattern in visit_counts)
- Worker retry in progress (failure_count > 0 with worker_active)
- Worker running >15 minutes without progress
- Orca log contains WARNING entries

Info-level:
- Issue completed successfully
- Pipeline approaching completion

**Workflow optimization:**
- Read session logs to understand what workers actually do
- Read prompt templates (discover from orca.yml) to compare instructions vs behavior
- Evaluate whether workflow design serves the task well
- Propose concrete orca.yml changes in remediation as markdown yaml code blocks
- Consider: merging/splitting states, adding/removing states, changing transitions, adjusting parallelism, improving prompts, tuning settings

**Sleep pattern:**
- After each investigation cycle, sleep for 300 seconds (5 minutes)
- Use: `! sleep 300` or the bash tool

**Termination:**
- Check state.json — when ALL issues have terminal states, write final summary and stop
- Final summary entry (severity: "summary"): elapsed time, issues completed/failed, worker stats, ordered remediation list

- [ ] **Step 2: Delete old template**

```bash
git rm src/orca/orchestrator/prompts/insights.md.j2
```

- [ ] **Step 3: Commit**

```bash
git add src/orca/orchestrator/prompts/insights.md
git commit -m "feat: add long-lived insights agent prompt, remove old template"
```

---

### Task 2: Remove old insights code

**Files:**
- Delete: `src/orca/orchestrator/insights.py`
- Modify: `src/orca/orchestrator/worker.py` — remove `execute_raw()`
- Modify: `src/orca/orchestrator/template.py` — remove `render_insights_prompt()`
- Modify: `src/orca/orchestrator/orchestrator.py` — remove `_run_insights_once`, `_insights_loop`, old constructor params
- Modify: `src/orca/orchestrator/runner.py` — remove `insights_worker` creation
- Modify: `tests/orchestrator/test_insights.py` — remove old tests
- Modify: `src/orca/tui/widgets/issue_detail.py` — remove `show_insights()`

- [ ] **Step 1: Delete insights.py**

```bash
git rm src/orca/orchestrator/insights.py
```

Remove any imports of `serialize_state_for_insights`, `truncate_insights_so_far`, `gather_transcripts` from orchestrator.py.

- [ ] **Step 2: Remove `execute_raw()` from worker.py**

Delete the `execute_raw()` method (lines 120-172). Remove any `execute_raw` imports.

- [ ] **Step 3: Remove `render_insights_prompt()` from template.py**

Delete the function. If it's the only function besides `render_prompt`, just remove it. Keep `render_prompt` (used by workers).

- [ ] **Step 4: Remove old insights from orchestrator.py**

Remove:
- `_run_insights_once()` method
- `_insights_loop()` method
- `insights_worker` constructor parameter and `self._insights_worker` field
- `self._insights_interval`, `self._insights_timeout`, `self._insights_in_flight` fields
- The `insights_task` creation and cancellation in `run()`
- The final `_run_insights_once()` call at end of `run()`
- Imports: `serialize_state_for_insights`, `truncate_insights_so_far`, `render_insights_prompt`

Add `insights_enabled: bool = False` as constructor parameter (replacing `insights_worker`), store as `self._insights_enabled`.

- [ ] **Step 5: Simplify runner.py**

Remove:
- `insights_worker = worker if insights_enabled else None` line
- `insights_worker=insights_worker` from Orchestrator constructor call

Replace with:
- `insights_enabled=insights_enabled` in Orchestrator constructor call

- [ ] **Step 6: Remove `show_insights()` from issue_detail.py**

Delete the method. Remove the `_refresh_md` / `refresh_transcript` code that was only used for insights.md auto-refresh. Keep `show_issue()` and `_last_failure_error()`.

- [ ] **Step 7: Update tests**

In `tests/orchestrator/test_insights.py`:
- Remove `TestSerializeStateForInsights` class
- Remove `TestTruncateInsightsSoFar` class
- Remove or update `TestInsightsIntegration` — will be rewritten in Task 3

Remove references to `execute_raw` in test_worker.py if any remain.

Update mock workers in test_orchestrator.py and test_integration.py if they reference `execute_raw`.

- [ ] **Step 8: Run tests and linters**

Run: `uv run ruff check . && uv run mypy src/ && uv run pytest tests/ -q`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: remove old insights pipeline (insights.py, execute_raw, insights.md.j2)"
```

---

### Task 3: Spawn insights as tmux session in orchestrator

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py`

- [ ] **Step 1: Add `_build_insights_prompt` method**

```python
def _build_insights_prompt(self) -> str:
    """Build the insights agent prompt with baked-in file paths."""
    prompt_path = Path(__file__).parent / "prompts" / "insights.md"
    template = prompt_path.read_text()
    run_dir = self.persistence.state_path.parent
    # Find config path
    config_path = ""
    if self.repo_root:
        # Look for orca.yml or orca.*.yml in repo root
        for candidate in self.repo_root.glob("orca*.yml"):
            config_path = str(candidate)
            break
    return template.format(
        run_dir=str(run_dir),
        branch_name=self.root_branch,
        config_path=config_path,
        repo_root=str(self.repo_root or "."),
    )
```

- [ ] **Step 2: Add insights tmux spawn in `run()` method**

At the start of `run()`, after the initial effects are routed:

```python
# Spawn insights agent as long-lived tmux session
insights_session: TmuxSession | None = None
insights_tracking_id = ""
if self._insights_enabled and self.repo_root is not None:
    from orca.orchestrator.pty_session import TmuxSession

    insights_tracking_id = f"insights-{uuid4()}"
    insights_session = TmuxSession(session_name=insights_tracking_id, cols=120, rows=40)

    prompt = self._build_insights_prompt()

    run_dir = self.persistence.state_path.parent
    log_dir = self.repo_root / ".orca" / "sessions"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    insights_log_path = log_dir / f"insights-{timestamp}.log"

    await insights_session.spawn(
        "claude",
        ["--dangerously-skip-permissions", "--max-turns", "200"],
        cwd=self.repo_root,
        stdin_data=prompt.encode(),
    )

    self._tmux_sessions[insights_tracking_id] = insights_session
    self._session_log_paths[insights_tracking_id] = str(insights_log_path)
```

- [ ] **Step 3: Add insights cleanup at end of `run()`**

After the main loop and worker cleanup:

```python
# Clean up insights session
if insights_session is not None:
    # Wait briefly for agent to notice completion and write summary
    await asyncio.sleep(10)
    # Final scrollback capture
    try:
        raw = insights_session.capture_scrollback()
        if raw and insights_tracking_id in self._session_log_paths:
            Path(self._session_log_paths[insights_tracking_id]).write_text(raw)
    except Exception:
        pass
    self._tmux_sessions.pop(insights_tracking_id, None)
    insights_session.close()
```

- [ ] **Step 4: Store insights_tracking_id for TUI access**

Add to constructor: `self._insights_tracking_id: str = ""`

Set it when spawning. The TUI needs this to show the insights session log when the Insights parent node is selected.

Expose via property:
```python
@property
def insights_tracking_id(self) -> str:
    return self._insights_tracking_id
```

- [ ] **Step 5: Run tests and linters**

Run: `uv run ruff check . && uv run mypy src/ && uv run pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py
git commit -m "feat: spawn insights agent as long-lived tmux session"
```

---

### Task 4: Add InsightEntrySelected message + insights.json reading in TUI

**Files:**
- Modify: `src/orca/tui/messages.py` — add `InsightEntrySelected`
- Modify: `src/orca/tui/widgets/issue_tree.py` — read `insights.json`, render as children
- Modify: `src/orca/tui/app.py` — handle `InsightEntrySelected`, update `on_insights_selected`

- [ ] **Step 1: Add InsightEntrySelected message**

```python
# In messages.py
class InsightEntrySelected(Message):
    """Posted when user selects an insight entry in the tree."""

    def __init__(self, title: str, detail: str, remediation: str, severity: str) -> None:
        super().__init__()
        self.title = title
        self.detail = detail
        self.remediation = remediation
        self.severity = severity
```

- [ ] **Step 2: Read insights.json in IssueTree**

Add a method to read and parse insights.json:

```python
def _read_insights(self, run_dir: Path) -> list[dict[str, Any]]:
    insights_path = run_dir / "insights.json"
    if not insights_path.exists():
        return []
    try:
        return json.loads(insights_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
```

The tree needs the `run_dir` path. Pass it via constructor or via `update_state`.

- [ ] **Step 3: Render insights entries as tree children**

In `update_state()`, when adding the Insights node, add children:

```python
if self._insights_enabled:
    insights_label = Text()
    insights_label.append("◆ ", style="bold cyan")
    insights_label.append("Insights", style="cyan")
    insights_node = self.root.add(insights_label, data="insights")
    insights_node.expand()

    # Add insight entries as children
    for i, entry in enumerate(self._read_insights(self._run_dir)):
        severity = entry.get("severity", "info")
        title = entry.get("title", "Untitled")
        entry_label = Text()
        if severity == "error":
            entry_label.append("● ", style="bold red")
        elif severity == "warning":
            entry_label.append("⚠ ", style="bold yellow")
        elif severity == "summary":
            entry_label.append("◆ ", style="bold cyan")
        else:
            entry_label.append("ℹ ", style="dim")
        entry_label.append(title[:60], style="dim" if severity == "info" else "")
        insights_node.add_leaf(entry_label, data=f"insight:{i}")
```

- [ ] **Step 4: Post InsightEntrySelected on highlight**

In `on_tree_node_highlighted`, handle `insight:` prefix:

```python
elif data.startswith("insight:"):
    idx = int(data[8:])
    entries = self._read_insights(self._run_dir)
    if 0 <= idx < len(entries):
        entry = entries[idx]
        self.post_message(InsightEntrySelected(
            title=str(entry.get("title", "")),
            detail=str(entry.get("detail", "")),
            remediation=str(entry.get("remediation", "")),
            severity=str(entry.get("severity", "info")),
        ))
```

- [ ] **Step 5: Update on_insights_selected in app.py**

When the Insights parent node is selected, show the insights session log (same as a worker session):

```python
def on_insights_selected(self, message: InsightsSelected) -> None:
    self._deselect_session()
    detail = self.query_one(IssueDetail)
    terminal = self.query_one(TerminalView)

    # Show insights session log if available
    insights_log = self._session_log_paths.get(self._insights_tracking_id, "")
    if insights_log:
        detail.styles.display = "none"
        terminal.styles.display = "block"
        self._selected_session_id = self._insights_tracking_id
        self._hot_sessions.add(self._insights_tracking_id)
        terminal.show_log_file(Path(insights_log), active=True)
    else:
        terminal.styles.display = "none"
        detail.styles.display = "block"
        detail.show_issue_text("Insights", "*Waiting for insights agent to start...*")
```

Add `_insights_tracking_id` to the app (passed from orchestrator via shared state or as a constructor param).

- [ ] **Step 6: Handle InsightEntrySelected in app.py**

Show the full detail + remediation as markdown:

```python
def on_insight_entry_selected(self, message: InsightEntrySelected) -> None:
    self._deselect_session()
    terminal = self.query_one(TerminalView)
    terminal.styles.display = "none"
    detail = self.query_one(IssueDetail)
    detail.styles.display = "block"

    # Build markdown content
    severity_icon = {"error": "●", "warning": "⚠", "info": "ℹ", "summary": "◆"}.get(message.severity, "ℹ")
    content = f"# {severity_icon} {message.title}\n\n"
    if message.detail:
        content += f"{message.detail}\n\n"
    if message.remediation:
        content += f"## Remediation\n\n{message.remediation}\n"

    detail.show_issue_text(message.title, content)
```

This requires a new `show_issue_text(title, markdown_content)` method on IssueDetail — a simple wrapper that updates the markdown widget.

- [ ] **Step 7: Add `show_issue_text()` to IssueDetail**

```python
def show_issue_text(self, title: str, content: str) -> None:
    """Display arbitrary markdown content."""
    self.stop_auto_refresh()
    self._markdown.update(content)
```

- [ ] **Step 8: Run tests and linters**

Run: `uv run ruff check . && uv run mypy src/ && uv run pytest tests/ -q`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: insights entries in TUI tree with markdown detail view"
```

---

### Task 5: Wire insights_tracking_id through runner to TUI

**Files:**
- Modify: `src/orca/orchestrator/runner.py`
- Modify: `src/orca/tui/app.py`
- Modify: `src/orca/tui/widgets/issue_tree.py`

The TUI needs:
1. `insights_tracking_id` — to look up the session log path for the Insights parent node
2. `run_dir` — for `issue_tree.py` to read `insights.json`

- [ ] **Step 1: Pass insights_tracking_id as shared state**

In runner.py, add a shared dict for the insights tracking ID (similar to `session_log_paths`):

```python
# In main(), non-headless branch:
insights_state: dict[str, str] = {}  # {"tracking_id": "insights-uuid"}
```

Pass to both `run()` and `OrcaApp`. The orchestrator writes `insights_state["tracking_id"]` when it spawns the insights session.

- [ ] **Step 2: Pass run_dir to IssueTree**

IssueTree already has `update_state()` called with state + sessions. Add `run_dir` to the constructor or pass it as a parameter. The simplest: pass `run_dir` in the constructor since it doesn't change.

```python
# In app.py compose():
yield IssueTree(insights_enabled=self._insights_enabled, config=self._config, run_dir=self._run_dir)
```

- [ ] **Step 3: Update OrcaApp to receive insights_state**

```python
def __init__(self, ..., insights_state: dict[str, str] | None = None):
    ...
    self._insights_state = insights_state or {}

@property
def _insights_tracking_id(self) -> str:
    return self._insights_state.get("tracking_id", "")
```

- [ ] **Step 4: Run tests and linters**

Run: `uv run ruff check . && uv run mypy src/ && uv run pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: wire insights tracking ID and run_dir through runner to TUI"
```

---

### Task 6: Write integration tests

**Files:**
- Modify: `tests/orchestrator/test_insights.py`

- [ ] **Step 1: Write test for insights prompt building**

```python
def test_build_insights_prompt_contains_paths(tmp_path: Path) -> None:
    """Prompt contains run_dir and branch_name."""
    # Create minimal orchestrator with persistence
    # Call _build_insights_prompt
    # Verify output contains the run_dir path
```

- [ ] **Step 2: Write test for insights.json reading in tree**

```python
def test_insights_tree_reads_entries(tmp_path: Path) -> None:
    """IssueTree reads insights.json and creates child nodes."""
    insights = [
        {"severity": "warning", "title": "Test warning", "detail": "...", "remediation": "..."},
        {"severity": "error", "title": "Test error", "detail": "...", "remediation": "..."},
    ]
    (tmp_path / "insights.json").write_text(json.dumps(insights))
    # Verify _read_insights returns 2 entries
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`

- [ ] **Step 4: Run linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: add insights redesign tests"
```

---

### Task 7: Final verification and cleanup

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`

- [ ] **Step 2: Run all linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`

- [ ] **Step 3: Check for stale imports**

Run: `uv run ruff check . --select F401`

- [ ] **Step 4: Verify no references to removed code**

```bash
grep -r "execute_raw\|serialize_state_for_insights\|truncate_insights\|render_insights_prompt\|insights\.md\.j2\|insights\.md" src/ --include="*.py" | grep -v "insights.json\|insights.md\b"
```

- [ ] **Step 5: Commit any cleanup**

```bash
git add -A
git commit -m "chore: final cleanup for insights redesign"
```
