from __future__ import annotations

from datetime import UTC, datetime

from orca.engine.types import Issue, State, StateMachineConfig


def _format_elapsed(created_ts: str, now: str) -> str:
    """Format elapsed time between created timestamp and now."""
    created = datetime.fromisoformat(created_ts)
    current = datetime.fromisoformat(now)
    # Ensure both are UTC-aware for correct diff
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    delta = current - created
    total_seconds = max(0, int(delta.total_seconds()))
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _get_created_timestamp(issue: Issue) -> str | None:
    """Find the 'created' event timestamp in the issue's event log."""
    for entry in issue.event_log:
        if entry.type == "created":
            return entry.timestamp
    return None


def _get_children(state: State, issue_id: str) -> list[str]:
    """Get child issue IDs sorted lexicographically."""
    children = [iid for iid, issue in state.issues.items() if issue.decomposed_from == issue_id]
    return sorted(children)


def _render_issue(
    state: State,
    config: StateMachineConfig,
    issue_id: str,
    now: str,
    prefix: str,
    connector: str,
) -> list[str]:
    """Render a single issue and its children recursively."""
    issue = state.issues[issue_id]
    state_def = config.get_state(issue.type, issue.state)
    is_terminal = state_def.terminal

    # Elapsed time
    created_ts = _get_created_timestamp(issue)
    elapsed = _format_elapsed(created_ts, now) if created_ts is not None else "?"

    # State marker
    marker = "" if is_terminal else " ..."

    state_label = f"[{issue.state}]" if issue.type == "default" else f"[{issue.type}:{issue.state}]"

    line = f"{prefix}{connector}{issue_id} {state_label}{marker} {elapsed}"
    lines: list[str] = [line]

    # Determine the continuation prefix for children/annotations
    if connector == "":
        child_prefix = prefix
    elif connector == "\u251c\u2500\u2500 ":
        child_prefix = prefix + "\u2502   "
    else:  # "└── "
        child_prefix = prefix + "    "

    # depends_on annotation
    if issue.depends_on:
        dep_str = ", ".join(sorted(issue.depends_on))
        lines.append(f"{child_prefix}\u2514\u2500\u2500 depends on: {dep_str}")

    # Children
    children = _get_children(state, issue_id)
    for i, child_id in enumerate(children):
        is_last = i == len(children) - 1
        child_connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        lines.extend(_render_issue(state, config, child_id, now, child_prefix, child_connector))

    return lines


def format_issues(state: State, config: StateMachineConfig, now: str) -> str:
    """Format the current state as an ASCII tree visualization."""
    if not state.issues:
        return ""

    # Find root issues (no decomposed_from), sorted by ID
    roots = sorted(iid for iid, issue in state.issues.items() if issue.decomposed_from is None)

    lines: list[str] = []

    for root_id in roots:
        children = _get_children(state, root_id)
        root_lines = _render_issue(state, config, root_id, now, "", "")

        if not children:
            lines.extend(root_lines)
        else:
            # Root with children: render root, then children with tree connectors
            issue = state.issues[root_id]
            state_def = config.get_state(issue.type, issue.state)
            is_terminal = state_def.terminal
            created_ts = _get_created_timestamp(issue)
            elapsed = _format_elapsed(created_ts, now) if created_ts is not None else "?"
            marker = "" if is_terminal else " ..."
            state_label = f"[{issue.state}]" if issue.type == "default" else f"[{issue.type}:{issue.state}]"
            lines.append(f"{root_id} {state_label}{marker} {elapsed}")

            # depends_on for root
            if issue.depends_on:
                dep_str = ", ".join(sorted(issue.depends_on))
                lines.append(f"\u2514\u2500\u2500 depends on: {dep_str}")

            for i, child_id in enumerate(children):
                is_last = i == len(children) - 1
                connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
                lines.extend(_render_issue(state, config, child_id, now, "", connector))

        lines.append("")  # blank line after each root tree

    # Worker queues
    for state_name in sorted(state.worker_queues.keys()):
        queue = state.worker_queues[state_name]
        if queue:
            lines.append(f"Queued in '{state_name}': {', '.join(queue)}")

    # Strip trailing blank lines, then join
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)
