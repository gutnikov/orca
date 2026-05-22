from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from orca.engine.types import (
    DispatchWorkerEffect,
    Effect,
    EnumFieldDef,
    EventLogEntry,
    Issue,
    ListFieldDef,
    State,
    StateMachineConfig,
    StringFieldDef,
)


def get_children(state: State, issue_id: str) -> list[str]:
    """Returns list of issue IDs where decomposed_from == issue_id."""
    return [iid for iid, issue in state.issues.items() if issue.decomposed_from == issue_id]


def is_blocked(state: State, config: StateMachineConfig, issue_id: str) -> bool:
    """Returns True if the issue is decomposition-blocked or dependency-blocked."""
    issue = state.issues[issue_id]

    # Decomposition-blocked: has children not all in terminal states
    children = get_children(state, issue_id)
    if children:
        for child_id in children:
            child = state.issues[child_id]
            if child.state != "done":
                return True

    # Dependency-blocked: has depends_on entries not all in terminal states
    for dep_id in issue.depends_on:
        dep = state.issues[dep_id]
        if dep.state != "done":
            return True

    return False


def build_issue_context(state: State, issue_id: str) -> dict[str, Any]:
    """Builds the issue context dict for DispatchWorkerEffect."""
    issue = state.issues[issue_id]
    children_ids = get_children(state, issue_id)
    children: list[dict[str, Any]] = []
    for child_id in children_ids:
        child = state.issues[child_id]
        children.append(
            {
                "issue_id": child_id,
                "fields": child.fields,
                "state": child.state,
                "event_log": [entry.to_dict() for entry in child.event_log],
            }
        )
    return {
        "fields": issue.fields,
        "event_log": [entry.to_dict() for entry in issue.event_log],
        "decomposed_from": issue.decomposed_from,
        "depends_on": issue.depends_on,
        "children": children,
    }


def build_result_format(config: StateMachineConfig, type_name: str, state_name: str) -> dict[str, Any]:
    """Serializes the result_format from config into a plain dict."""
    state_def = config.get_state(type_name, state_name)
    if state_def.worker is None:
        return {}
    result: dict[str, Any] = {}
    for name, field_def in state_def.worker.result_format.items():
        if isinstance(field_def, EnumFieldDef):
            result[name] = {
                "type": "enum",
                "values": field_def.values,
                "description": field_def.description,
                "values_description": field_def.values_description,
            }
        elif isinstance(field_def, StringFieldDef):
            result[name] = {
                "type": "string",
                "description": field_def.description,
                "required_when": field_def.required_when,
            }
        elif isinstance(field_def, ListFieldDef):
            result[name] = {
                "type": "list",
                "description": field_def.description,
                "items": field_def.items,
                "required_when": field_def.required_when,
            }
    return result


def append_log(issue: Issue, timestamp: str, entry_type: str, data: dict[str, Any]) -> None:
    """Append an event log entry to an issue."""
    issue.event_log.append(EventLogEntry(timestamp=timestamp, type=entry_type, data=data))


def try_dispatch(
    config: StateMachineConfig,
    state: State,
    issue_id: str,
    effects: list[Effect],
) -> None:
    """Core dispatch protocol."""
    issue = state.issues[issue_id]
    state_name = issue.state
    state_def = config.get_state(issue.type, state_name)

    # 1. If issue is blocked, don't dispatch
    if is_blocked(state, config, issue_id):
        return

    # 2. If state has no worker, don't dispatch
    if state_def.worker is None:
        return

    # 3. If state has max_workers and active count >= limit, queue the issue
    if state_def.max_workers is not None:
        # Count active workers matching BOTH type and state
        active_count = sum(
            1
            for iss in state.issues.values()
            if iss.type == issue.type and iss.state == state_name and iss.worker_active
        )
        if active_count >= state_def.max_workers:
            queue_key = f"{issue.type}:{state_name}"
            queue = state.worker_queues.setdefault(queue_key, [])
            queue.append(issue_id)
            return

    # 4. Dispatch
    issue.worker_active = True
    effects.append(
        DispatchWorkerEffect(
            issue_id=issue_id,
            issue_type=issue.type,
            state=state_name,
            result_format=build_result_format(config, issue.type, state_name),
            issue=build_issue_context(state, issue_id),
            progress_enabled=state_def.worker.progress,
        )
    )


def backfill_queue(
    config: StateMachineConfig,
    state: State,
    queue_key: str,
    effects: list[Effect],
) -> None:
    """When a slot frees up in a capped state, pop next non-blocked issue from queue and dispatch."""
    queue = state.worker_queues.get(queue_key)
    if not queue:
        return

    # Find next non-blocked issue in queue
    for i, issue_id in enumerate(queue):
        if not is_blocked(state, config, issue_id):
            queue.pop(i)
            try_dispatch(config, state, issue_id, effects)
            return


def remove_from_queue(state: State, queue_key: str, issue_id: str) -> None:
    """Remove an issue from a state's queue."""
    queue = state.worker_queues.get(queue_key)
    if queue is None:
        return
    with contextlib.suppress(ValueError):
        queue.remove(issue_id)


def _format_duration(started_at: str, completed_at: str) -> str:
    """Format duration between two ISO timestamps as human-readable string."""
    from datetime import datetime

    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
        total = int((end - start).total_seconds())
        if total < 0:
            total = 0
        minutes, seconds = divmod(total, 60)
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"
    except (ValueError, TypeError):
        return ""


def _last_state_before_result(event_log: list[EventLogEntry], result_entry: EventLogEntry) -> str:
    """Find the state name for a worker_result by looking at the preceding worker_dispatched entry."""
    last_state = ""
    for entry in event_log:
        if entry is result_entry:
            break
        if entry.type == "worker_dispatched":
            last_state = entry.data.get("state", "")
    return last_state


def build_run_context(
    state: State,
    run_dir: Path,
    sessions_dir: Path,
    sessions: list[dict[str, Any]],
    branch: str,
    workflow: str,
) -> dict[str, Any]:
    """Build the run context dict for Jinja2 templates."""
    insights_path = run_dir / "insights.json"
    repo_root = sessions_dir.parent.parent if sessions_dir.parent.name == ".orca-state" else sessions_dir.parent
    ctx: dict[str, Any] = {
        "repo_root": str(repo_root),
        "run_dir": str(run_dir),
        "log": str(run_dir / "orca.log.jsonl"),
        "insights": str(insights_path) if insights_path.exists() else None,
        "state": str(run_dir / "state.json"),
        "sessions_dir": str(sessions_dir),
        "branch": branch,
        "workflow": workflow,
    }

    # Sessions list
    ctx["sessions"] = []
    for s in sessions:
        entry: dict[str, Any] = {"state": s.get("state", "")}
        entry["log"] = s.get("log_path", "")
        started = s.get("started_at", "")
        completed = s.get("completed_at", "")
        entry["duration"] = _format_duration(started, completed) if completed else ""
        entry["outcome"] = s.get("outcome", "")
        ctx["sessions"].append(entry)

    # Summary from root issue event log
    states_visited: list[str] = []
    current_state = ""
    outcomes: dict[str, str] = {}
    failures: dict[str, str] = {}

    for issue in state.issues.values():
        current_state = issue.state
        states_visited = list(issue.visit_counts.keys())
        for log_entry in issue.event_log:
            if log_entry.type == "worker_result":
                state_name = _last_state_before_result(issue.event_log, log_entry)
                if state_name and log_entry.data.get("outcome"):
                    outcomes[state_name] = log_entry.data["outcome"]
            elif log_entry.type == "worker_failed":
                state_name = log_entry.data.get("state", "")
                error = log_entry.data.get("error", "unknown error")
                if state_name:
                    failures[state_name] = error

    total_duration = ""
    if sessions:
        starts = [s.get("started_at", "") for s in sessions if s.get("started_at")]
        ends = [s.get("completed_at", "") for s in sessions if s.get("completed_at")]
        if starts and ends:
            total_duration = _format_duration(min(starts), max(ends))

    ctx["summary"] = {
        "states_visited": states_visited,
        "current_state": current_state,
        "outcomes": outcomes,
        "failures": failures,
        "total_duration": total_duration,
    }

    ctx["formats"] = {
        "log": "JSONL, one event per line: {timestamp, level, logger, message, event, ...}",
        "insights": "JSON array of {timestamp, severity, title, detail, remediation}",
        "state": "JSON snapshot of all issues: {issues: {id: {type, fields, state, event_log, ...}}}",
        "sessions": "Plain text terminal scrollback from each worker session",
    }

    return ctx
