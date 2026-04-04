from __future__ import annotations

import copy
from collections.abc import Callable

from orca.engine.dispatch import (
    append_log,
    backfill_queue,
    build_issue_context,
    build_result_format,
    get_children,
    is_blocked,
    remove_from_queue,
    try_dispatch,
)
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    Effect,
    ErrorEffect,
    Event,
    Issue,
    OnDecompose,
    OnTransition,
    State,
    StateMachineConfig,
    WorkerFailedEvent,
    WorkerResultEvent,
    WorkerResumedEvent,
    WorkerWaitingEvent,
)


def reduce(
    config: StateMachineConfig,
    state: State,
    event: Event,
    generate_id: Callable[[], str],
    now: Callable[[], str],
) -> tuple[State, list[Effect]]:
    """Dispatch event to the appropriate handler and return (new_state, effects)."""
    new_state = copy.deepcopy(state)
    effects: list[Effect] = []
    ts = now()

    if isinstance(event, CreateEvent):
        _handle_create(config, new_state, event, effects, ts)
    elif isinstance(event, AdvanceEvent):
        _handle_advance(config, new_state, event, effects, ts)
    elif isinstance(event, WorkerResultEvent):
        _handle_worker_result(config, new_state, event, effects, generate_id, ts)
    elif isinstance(event, WorkerFailedEvent):
        _handle_worker_failed(config, new_state, event, effects, ts)
    elif isinstance(event, WorkerWaitingEvent):
        _handle_worker_waiting(config, new_state, event, effects, ts)
    elif isinstance(event, WorkerResumedEvent):
        _handle_worker_resumed(config, new_state, event, effects, ts)

    return new_state, effects


def _handle_create(
    config: StateMachineConfig,
    state: State,
    event: CreateEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    if event.issue_id in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' already exists"))
        return

    root_td = config.root_type_def
    issue = Issue(
        type=config.root_type,
        fields=event.fields,
        state=root_td.initial,
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
        visit_counts={root_td.initial: 1},
        hop_count=0,
    )
    state.issues[event.issue_id] = issue

    # Log the creation
    append_log(issue, event.timestamp, "created", {"state": root_td.initial})

    # If initial state is active (has a worker), dispatch
    state_def = config.get_state(config.root_type, root_td.initial)
    if state_def.worker is not None:
        prev_len = len(effects)
        try_dispatch(config, state, event.issue_id, effects)
        if len(effects) > prev_len:
            append_log(issue, ts, "worker_dispatched", {"state": issue.state})


def _handle_advance(
    config: StateMachineConfig,
    state: State,
    event: AdvanceEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    # Issue must exist
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]
    current_state_def = config.get_state(issue.type, issue.state)

    # Must be in a passive state (no worker and not terminal)
    if current_state_def.worker is not None or issue.state == "done":
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"Issue '{event.issue_id}' is not in a passive state (current: '{issue.state}')",
            )
        )
        return

    # Must not be blocked
    if is_blocked(state, config, event.issue_id):
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"Issue '{event.issue_id}' is blocked",
            )
        )
        return

    # Target state must exist in the issue's type (or be a builtin)
    from orca.engine.types import BUILTIN_STATES

    type_def = config.get_type(issue.type)
    if event.target_state not in type_def.states and event.target_state not in BUILTIN_STATES:
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"State '{event.target_state}' does not exist in config",
            )
        )
        return

    old_state = issue.state

    # Hop limit checks before moving
    target_state_def = config.get_state(issue.type, event.target_state)
    if config.max_hops is not None and issue.hop_count + 1 > config.max_hops:
        append_log(issue, ts, "limit_reached", {"limit": "max_hops", "count": issue.hop_count + 1})
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"max_hops ({config.max_hops}) reached",
            )
        )
        return

    # Move to target state
    issue.state = event.target_state

    # Log the advance
    append_log(issue, event.timestamp, "advanced", {"from": old_state, "to": event.target_state})

    # Update visit counts and hop count
    issue.visit_counts[event.target_state] = issue.visit_counts.get(event.target_state, 0) + 1
    issue.hop_count += 1
    if target_state_def.worker is not None:
        prev_len = len(effects)
        try_dispatch(config, state, event.issue_id, effects)
        if len(effects) > prev_len:
            append_log(issue, ts, "worker_dispatched", {"state": issue.state})


def _handle_worker_result(
    config: StateMachineConfig,
    state: State,
    event: WorkerResultEvent,
    effects: list[Effect],
    generate_id: Callable[[], str],
    ts: str,
) -> None:
    # --- Validation (before any mutation) ---

    # Issue must exist
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]
    state_def = config.get_state(issue.type, issue.state)

    # Issue must not be in terminal state
    if issue.state == "done":
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"Issue '{event.issue_id}' is in terminal state '{issue.state}'",
            )
        )
        return

    # Issue must have worker_active == True
    if not issue.worker_active:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' has worker_active=False")
        )
        return

    # Issue must not be blocked
    if is_blocked(state, config, event.issue_id):
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is blocked"))
        return

    # State must have a worker
    if state_def.worker is None:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"State '{issue.state}' has no worker"))
        return

    # outcome must exist in result and be in state_def.on
    outcome = event.result.get("outcome")

    if outcome is None or outcome not in state_def.on:
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"Outcome '{outcome}' is not valid for state '{issue.state}'",
            )
        )
        return

    rule = state_def.on[outcome]

    # Handle built-in "failed" target: treat as worker failure (retry logic)
    if isinstance(rule, OnTransition) and rule.target == "failed":
        reason = str(event.result.get("reason", "Worker returned failure outcome"))
        issue.worker_active = False
        issue.failure_count += 1

        append_log(issue, event.timestamp, "worker_result", event.result)
        append_log(issue, ts, "worker_failed", {"state": issue.state, "error": reason})

        # Store reason in issue fields if the type defines failure_context
        issue_fields_def = config.get_type(issue.type).fields
        if "failure_context" in issue_fields_def:
            issue.fields["failure_context"] = reason

        # Slot backfill
        old_state_name = issue.state
        if state_def.max_workers is not None:
            backfill_queue(config, state, f"{issue.type}:{old_state_name}", effects)

        # Check retry limit
        if config.max_worker_retries is not None and issue.failure_count >= config.max_worker_retries:
            append_log(
                issue,
                ts,
                "worker_retries_exhausted",
                {"state": issue.state, "failure_count": issue.failure_count},
            )
            effects.append(
                ErrorEffect(
                    issue_id=event.issue_id,
                    message=f"Issue '{event.issue_id}' failed {issue.failure_count} times in state "
                    f"'{issue.state}' — retries exhausted",
                )
            )
            return

        # Retry — re-dispatch
        issue.worker_active = True
        append_log(issue, ts, "worker_dispatched", {"state": issue.state})
        effects.append(
            DispatchWorkerEffect(
                issue_id=event.issue_id,
                issue_type=issue.type,
                state=issue.state,
                result_format=build_result_format(config, issue.type, issue.state),
                issue=build_issue_context(state, event.issue_id),
            )
        )
        return

    # If decompose, validate sub_issues is not empty (before mutation)
    if isinstance(rule, OnDecompose):
        sub_issues: list[dict[str, object]] = event.result.get("sub_issues", [])
        if not sub_issues:
            effects.append(ErrorEffect(issue_id=event.issue_id, message="Decompose requires non-empty sub_issues"))
            return

    # --- Mutation ---

    old_state_name = issue.state

    # 1. Set worker_active = False (frees slot), reset failure count
    issue.worker_active = False
    issue.failure_count = 0

    # 2. Append worker_result log entry
    append_log(issue, event.timestamp, "worker_result", event.result)

    # 3. Merge result fields (except outcome) back into issue fields
    issue_fields = config.get_type(issue.type).fields
    for key, value in event.result.items():
        if key != "outcome" and key in issue_fields:
            issue.fields[key] = value

    # Slot backfill: if old state has max_workers, backfill
    dispatch_effects: list[Effect] = []
    if state_def.max_workers is not None:
        backfill_queue(config, state, f"{issue.type}:{old_state_name}", dispatch_effects)

    # 3. Hop limit checks before transition/decompose
    if isinstance(rule, OnTransition) and config.max_hops is not None and issue.hop_count + 1 > config.max_hops:
        append_log(issue, ts, "limit_reached", {"limit": "max_hops", "count": issue.hop_count + 1})
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"max_hops ({config.max_hops}) reached",
            )
        )
        effects.extend(dispatch_effects)
        return

    if isinstance(rule, OnDecompose) and config.max_hops is not None and issue.hop_count + 1 > config.max_hops:
        append_log(issue, ts, "limit_reached", {"limit": "max_hops", "count": issue.hop_count + 1})
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"max_hops ({config.max_hops}) reached",
            )
        )
        effects.extend(dispatch_effects)
        return

    # 4. Route based on rule type
    if isinstance(rule, OnTransition):
        _apply_transition(config, state, event.issue_id, issue, old_state_name, rule.target, dispatch_effects, ts)
    elif isinstance(rule, OnDecompose):
        _apply_decompose(config, state, event, issue, generate_id, dispatch_effects, ts)

    effects.extend(dispatch_effects)


def _handle_worker_failed(
    config: StateMachineConfig,
    state: State,
    event: WorkerFailedEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    # Issue must exist
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]
    state_def = config.get_state(issue.type, issue.state)

    # Issue must have worker_active == True
    if not issue.worker_active:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' has worker_active=False")
        )
        return

    # State must have a worker
    if state_def.worker is None:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"State '{issue.state}' has no worker"))
        return

    # Log the failure and increment failure count
    issue.failure_count += 1
    append_log(issue, event.timestamp, "worker_failed", {"state": issue.state, "error": event.error})

    # Store the failure error in issue fields so retry prompts can reference it
    issue_fields = config.get_type(issue.type).fields
    if "failure_context" in issue_fields:
        issue.fields["failure_context"] = event.error

    # Check retry limit
    if config.max_worker_retries is not None and issue.failure_count >= config.max_worker_retries:
        # Give up — release the worker slot and log
        issue.worker_active = False
        append_log(
            issue,
            ts,
            "worker_retries_exhausted",
            {"state": issue.state, "failure_count": issue.failure_count},
        )
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"Issue '{event.issue_id}' failed {issue.failure_count} times in state "
                f"'{issue.state}' — retries exhausted",
            )
        )
        return

    # Retry — worker_active stays True, slot is RETAINED
    append_log(issue, ts, "worker_dispatched", {"state": issue.state})
    effects.append(
        DispatchWorkerEffect(
            issue_id=event.issue_id,
            issue_type=issue.type,
            state=issue.state,
            result_format=build_result_format(config, issue.type, issue.state),
            issue=build_issue_context(state, event.issue_id),
        )
    )


def _handle_worker_waiting(
    config: StateMachineConfig,
    state: State,
    event: WorkerWaitingEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]

    if issue.state == "done":
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is in terminal state 'done'")
        )
        return

    if not issue.worker_active:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' has worker_active=False")
        )
        return

    append_log(issue, event.timestamp, "worker_waiting", {})


def _handle_worker_resumed(
    config: StateMachineConfig,
    state: State,
    event: WorkerResumedEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]

    if issue.state == "done":
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is in terminal state 'done'")
        )
        return

    if not issue.worker_active:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' has worker_active=False")
        )
        return

    append_log(issue, event.timestamp, "worker_resumed", {"message": event.message})


def _apply_transition(
    config: StateMachineConfig,
    state: State,
    issue_id: str,
    issue: Issue,
    old_state_name: str,
    target_state: str,
    effects: list[Effect],
    ts: str,
) -> None:
    # Remove issue from old state's worker queue
    remove_from_queue(state, f"{issue.type}:{old_state_name}", issue_id)

    # Move issue to target state
    issue.state = target_state
    target_def = config.get_state(issue.type, target_state)

    # Log the transition
    append_log(issue, ts, "transitioned", {"from": old_state_name, "to": target_state})

    # Update visit counts and hop count
    issue.visit_counts[target_state] = issue.visit_counts.get(target_state, 0) + 1
    issue.hop_count += 1

    if target_state == "done":
        # Run cascading unblock check
        _cascading_unblock(config, state, issue_id, effects, ts)
    elif target_def.worker is not None:
        # Target is active -> dispatch
        prev_len = len(effects)
        try_dispatch(config, state, issue_id, effects)
        if len(effects) > prev_len:
            append_log(issue, ts, "worker_dispatched", {"state": issue.state})


def _apply_decompose(
    config: StateMachineConfig,
    state: State,
    event: WorkerResultEvent,
    _parent_issue: Issue,
    generate_id: Callable[[], str],
    effects: list[Effect],
    ts: str,
) -> None:
    sub_issues: list[dict[str, object]] = event.result.get("sub_issues", [])

    # Increment parent hop count
    _parent_issue.hop_count += 1

    # Get default child_type from decompose rule
    parent_state_def = config.get_state(_parent_issue.type, _parent_issue.state)
    outcome: str = event.result["outcome"]
    rule = parent_state_def.on[outcome]
    assert isinstance(rule, OnDecompose)
    default_child_type = rule.child_type
    parent_old_state = _parent_issue.state

    # Generate IDs and build key -> real_id mapping
    key_to_id: dict[str, str] = {}
    for sub in sub_issues:
        key = str(sub.get("key", ""))
        real_id = generate_id()
        key_to_id[key] = real_id

    # Create child issues
    for sub in sub_issues:
        key = str(sub.get("key", ""))
        real_id = key_to_id[key]
        fields: dict[str, object] = sub.get("fields", {})  # type: ignore[assignment]

        # Resolve child type: worker override > rule default
        child_type_name = str(sub.get("type", "")) if "type" in sub else None
        if not child_type_name:
            child_type_name = default_child_type
        if not child_type_name:
            effects.append(
                ErrorEffect(
                    issue_id=event.issue_id,
                    message=f"No type for child '{key}': decompose rule has no child_type "
                    "and worker didn't specify one",
                )
            )
            return
        if child_type_name not in config.types:
            effects.append(
                ErrorEffect(
                    issue_id=event.issue_id,
                    message=f"Unknown type '{child_type_name}' for child '{key}'",
                )
            )
            return

        child_type_def = config.get_type(child_type_name)

        # Resolve depends_on keys to real IDs
        raw_depends: list[str] = sub.get("depends_on", [])  # type: ignore[assignment]
        resolved_depends: list[str] = [key_to_id[dk] for dk in raw_depends if dk in key_to_id]

        child = Issue(
            type=child_type_name,
            fields=dict(fields),
            state=child_type_def.initial,
            worker_active=False,
            decomposed_from=event.issue_id,
            depends_on=resolved_depends,
            event_log=[],
            visit_counts={child_type_def.initial: 1},
            hop_count=0,
        )
        state.issues[real_id] = child

        # Log creation on child
        append_log(child, ts, "created", {"state": child_type_def.initial})

        # If child has dependencies, log dependency_blocked
        if resolved_depends:
            append_log(child, ts, "dependency_blocked", {"depends_on": resolved_depends})

    # Dispatch non-blocked children
    for _key, real_id in key_to_id.items():
        child = state.issues[real_id]
        child_type_def = config.get_type(child.type)
        initial_def = child_type_def.states[child_type_def.initial]
        if initial_def.worker is not None and not is_blocked(state, config, real_id):
            prev_len = len(effects)
            try_dispatch(config, state, real_id, effects)
            if len(effects) > prev_len:
                append_log(child, ts, "worker_dispatched", {"state": child.state})

    # If decompose rule has a `then` target, transition parent immediately (children run independently)
    if rule.then is not None:
        remove_from_queue(state, f"{_parent_issue.type}:{parent_old_state}", event.issue_id)
        _apply_transition(config, state, event.issue_id, _parent_issue, parent_old_state, rule.then, effects, ts)
    else:
        # No `then` — parent is blocked until all children complete
        append_log(_parent_issue, ts, "decomposition_blocked", {})


def _find_decompose_rule(config: StateMachineConfig, type_name: str, state_name: str) -> OnDecompose | None:
    """Find the OnDecompose rule in the given state's on-rules, if any."""
    type_def = config.types.get(type_name)
    if type_def is None:
        return None
    state_def = type_def.states.get(state_name)
    if state_def is None:
        return None
    for rule in state_def.on.values():
        if isinstance(rule, OnDecompose):
            return rule
    return None


def _cascading_unblock(
    config: StateMachineConfig,
    state: State,
    terminal_issue_id: str,
    effects: list[Effect],
    ts: str,
) -> None:
    terminal_issue = state.issues[terminal_issue_id]

    # 1. Decomposition unblock: if this issue has a parent, check if all siblings are terminal
    if terminal_issue.decomposed_from is not None:
        parent_id = terminal_issue.decomposed_from
        parent = state.issues[parent_id]
        children = get_children(state, parent_id)
        all_terminal = all(state.issues[cid].state == "done" for cid in children)
        if all_terminal and not parent.worker_active:
            # Log unblocked on parent
            append_log(parent, ts, "unblocked", {"reason": "decomposition"})

            # Find the decompose rule that created these children to check for `then`
            decompose_rule = _find_decompose_rule(config, parent.type, parent.state)
            if decompose_rule is not None and decompose_rule.then is not None:
                # Transition parent to the `then` target
                old_state = parent.state
                _apply_transition(config, state, parent_id, parent, old_state, decompose_rule.then, effects, ts)
            else:
                # No `then` — re-dispatch parent in its current state (legacy behavior)
                prev_len = len(effects)
                try_dispatch(config, state, parent_id, effects)
                if len(effects) > prev_len:
                    append_log(parent, ts, "worker_dispatched", {"state": parent.state})

    # 2. Dependency unblock: find all issues that depend on the terminal issue
    for iid, iss in state.issues.items():
        if terminal_issue_id in iss.depends_on:
            # Check if all depends_on are now terminal
            all_deps_terminal = all(state.issues[dep_id].state == "done" for dep_id in iss.depends_on)
            if (
                all_deps_terminal
                and not is_blocked(state, config, iid)
                and not iss.worker_active
                and config.get_state(iss.type, iss.state).worker is not None
            ):
                # Log unblocked on the dependent issue
                append_log(iss, ts, "unblocked", {"reason": "dependency"})
                prev_len = len(effects)
                try_dispatch(config, state, iid, effects)
                if len(effects) > prev_len:
                    append_log(iss, ts, "worker_dispatched", {"state": iss.state})
