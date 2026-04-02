# Run Context in Worker Prompts

## Problem

Workers currently see only their own issue — fields, event log, and direct children. They have no visibility into the broader run: what states were visited, what outcomes occurred, where session logs and insights live. This makes it impossible to write "retro" or "post-mortem" workflow steps that review what happened across the entire run.

## Design

Expose a `run` Jinja2 variable in all worker prompt templates. Template authors reference it when needed; workers that don't care about run context simply don't use it.

### The `run` variable

Available in all templates alongside `issue`, `result_format`, and `result_path`.

#### File map

Paths to run artifacts so the agent can read them on demand:

```python
run = {
    "run_dir": "/abs/path/.orca/runs/BRANCH/WORKFLOW",
    "log": "/abs/path/.orca/runs/BRANCH/WORKFLOW/orca.log.jsonl",
    "insights": "/abs/path/.orca/runs/BRANCH/WORKFLOW/insights.json",  # None if not present
    "state": "/abs/path/.orca/runs/BRANCH/WORKFLOW/state.json",
    "sessions_dir": "/abs/path/.orca/sessions",
    "branch": "SMEW-1942_ai_team_prd_3",
    "workflow": "prd",
}
```

#### Sessions list

Per-session metadata with paths to logs:

```python
run["sessions"] = [
    {
        "state": "generate_prd",
        "log": "/abs/path/.orca/sessions/generate_prd-20260402T062633.log",
        "outcome": "complete",
        "duration": "6m 14s",
    },
    {
        "state": "territory_map",
        "log": "/abs/path/.orca/sessions/territory_map-20260402T064035.log",
        "outcome": "done",
        "duration": "1m 52s",
    },
    ...
]
```

#### Summary

Short structured summary so templates don't need to parse log files for basic facts:

```python
run["summary"] = {
    "states_visited": ["generate_prd", "territory_map", "build_and_run"],
    "current_state": "recon_prd",
    "outcomes": {
        "generate_prd": "complete",
        "territory_map": "done",
        "build_and_run": "done",
    },
    "failures": {
        "recon_prd": "Chrome DevTools MCP server not available",
    },
    "total_duration": "45m 12s",
}
```

#### File format descriptions

So templates can explain file formats to the agent:

```python
run["formats"] = {
    "log": "JSONL, one event per line: {timestamp, level, logger, message, event, ...}",
    "insights": "JSON array of {timestamp, severity, title, detail, remediation}",
    "state": "JSON snapshot of all issues: {issues: {id: {type, fields, state, event_log, ...}}}",
    "sessions": "Plain text terminal scrollback from each worker session",
}
```

### Template usage

A retro/post-mortem prompt:

```jinja2
## Run Summary
Branch: {{ run.branch }} | Workflow: {{ run.workflow }}
States visited: {{ run.summary.states_visited | join(", ") }}

{% if run.summary.failures %}
## Failures
{% for state, reason in run.summary.failures.items() %}
- **{{ state }}**: {{ reason }}
{% endfor %}
{% endif %}

## Session Logs
{% for s in run.sessions %}
- {{ s.state }} ({{ s.outcome }}, {{ s.duration }}): `{{ s.log }}`
{% endfor %}

## Files
- Structured event log: `{{ run.log }}`
- State snapshot: `{{ run.state }}`
{% if run.insights %}- Insights: `{{ run.insights }}`{% endif %}
```

A normal worker that doesn't need run context just doesn't reference `{{ run }}`.

### Implementation

#### New function: `build_run_context()` in `engine/dispatch.py`

Builds the `run` dict from:
- `State` — extract visited states, outcomes, failures from issue event logs
- `SessionManifest` — session list with paths, durations, outcomes
- Run directory path — absolute paths to log, insights, state files

Signature:

```python
def build_run_context(
    state: State,
    config: StateMachineConfig,
    run_dir: Path,
    sessions_dir: Path,
    sessions: list[dict[str, Any]],
    branch: str,
    workflow: str,
) -> dict[str, Any]:
```

#### Update `render_prompt()` in `orchestrator/template.py`

Add `run` parameter (default `None`). Add to Jinja2 context:

```python
context = {
    "issue": issue,
    "result_format": result_format,
    "result_path": str(result_path),
    "run": run,
}
```

#### Update worker dispatch path in `orchestrator/orchestrator.py`

Build run context before calling `worker.execute()`. Pass it through so `render_prompt` receives it. The orchestrator already has access to `State`, `SessionManifest`, run directory, branch, and workflow.

### What stays the same

- `issue`, `result_format`, `result_path` template variables — unchanged
- Worker protocol (result.json) — unchanged
- Engine types and reducer — unchanged (run context is built at the orchestrator layer, not the engine layer)
- Templates that don't use `{{ run }}` — unaffected
