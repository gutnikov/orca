from __future__ import annotations

import copy
from collections.abc import Callable

from orca.engine.dispatch import (
    backfill_queue,
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
    ResultHistoryEntry,
    State,
    StateMachineConfig,
    WorkerFailedEvent,
    WorkerResultEvent,
)


def reduce(
    config: StateMachineConfig,
    state: State,
    event: Event,
    generate_id: Callable[[], str],
) -> tuple[State, list[Effect]]:
    """Dispatch event to the appropriate handler and return (new_state, effects)."""
    new_state = copy.deepcopy(state)
    effects: list[Effect] = []

    if isinstance(event, CreateEvent):
        _handle_create(config, new_state, event, effects)
    elif isinstance(event, AdvanceEvent):
        _handle_advance(config, new_state, event, effects)
    elif isinstance(event, WorkerResultEvent):
        _handle_worker_result(config, new_state, event, effects, generate_id)
    elif isinstance(event, WorkerFailedEvent):
        pass

    return new_state, effects


def _handle_create(
    config: StateMachineConfig,
    state: State,
    event: CreateEvent,
    effects: list[Effect],
) -> None:
    if event.issue_id in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' already exists"))
        return

    issue = Issue(
        fields=event.fields,
        state=config.initial,
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        result_history=[],
    )
    state.issues[event.issue_id] = issue

    # If initial state is active (has a worker), dispatch
    state_def = config.states[config.initial]
    if state_def.worker is not None:
        dispatch_effects: list[DispatchWorkerEffect] = []
        try_dispatch(config, state, event.issue_id, dispatch_effects)
        effects.extend(dispatch_effects)


def _handle_advance(
    config: StateMachineConfig,
    state: State,
    event: AdvanceEvent,
    effects: list[Effect],
) -> None:
    # Issue must exist
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]
    current_state_def = config.states[issue.state]

    # Must be in a passive state (no worker and not terminal)
    if current_state_def.worker is not None or current_state_def.terminal:
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

    # Target state must exist
    if event.target_state not in config.states:
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"State '{event.target_state}' does not exist in config",
            )
        )
        return

    # Move to target state
    issue.state = event.target_state

    # If target state is active, dispatch
    target_state_def = config.states[event.target_state]
    if target_state_def.worker is not None:
        dispatch_effects: list[DispatchWorkerEffect] = []
        try_dispatch(config, state, event.issue_id, dispatch_effects)
        effects.extend(dispatch_effects)


def _handle_worker_result(
    config: StateMachineConfig,
    state: State,
    event: WorkerResultEvent,
    effects: list[Effect],
    generate_id: Callable[[], str],
) -> None:
    # --- Validation (before any mutation) ---

    # Issue must exist
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]
    state_def = config.states[issue.state]

    # Issue must not be in terminal state
    if state_def.terminal:
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

    # If decompose, validate sub_issues is not empty (before mutation)
    if isinstance(rule, OnDecompose):
        sub_issues: list[dict[str, object]] = event.result.get("sub_issues", [])
        if not sub_issues:
            effects.append(ErrorEffect(issue_id=event.issue_id, message="Decompose requires non-empty sub_issues"))
            return

    # --- Mutation ---

    old_state_name = issue.state

    # 1. Set worker_active = False (frees slot)
    issue.worker_active = False

    # 2. Append ResultHistoryEntry
    issue.result_history.append(ResultHistoryEntry(state=issue.state, result=event.result))

    # Slot backfill: if old state has max_workers, backfill
    dispatch_effects: list[DispatchWorkerEffect] = []
    if state_def.max_workers is not None:
        backfill_queue(config, state, old_state_name, dispatch_effects)

    # 3. Route based on rule type
    if isinstance(rule, OnTransition):
        _apply_transition(config, state, event.issue_id, issue, old_state_name, rule.target, dispatch_effects)
    elif isinstance(rule, OnDecompose):
        _apply_decompose(config, state, event, issue, generate_id, dispatch_effects)

    effects.extend(dispatch_effects)


def _apply_transition(
    config: StateMachineConfig,
    state: State,
    issue_id: str,
    issue: Issue,
    old_state_name: str,
    target_state: str,
    effects: list[DispatchWorkerEffect],
) -> None:
    # Remove issue from old state's worker queue
    remove_from_queue(state, old_state_name, issue_id)

    # Move issue to target state
    issue.state = target_state
    target_def = config.states[target_state]

    if target_def.terminal:
        # Run cascading unblock check
        _cascading_unblock(config, state, issue_id, effects)
    elif target_def.worker is not None:
        # Target is active -> dispatch
        try_dispatch(config, state, issue_id, effects)


def _apply_decompose(
    config: StateMachineConfig,
    state: State,
    event: WorkerResultEvent,
    _parent_issue: Issue,
    generate_id: Callable[[], str],
    effects: list[DispatchWorkerEffect],
) -> None:
    sub_issues: list[dict[str, object]] = event.result.get("sub_issues", [])

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

        # Resolve depends_on keys to real IDs
        raw_depends: list[str] = sub.get("depends_on", [])  # type: ignore[assignment]
        resolved_depends: list[str] = []
        for dep_key in raw_depends:
            if dep_key not in key_to_id:
                # This shouldn't happen if spec is followed, but handle it
                pass
            else:
                resolved_depends.append(key_to_id[dep_key])

        child = Issue(
            fields=dict(fields),
            state=config.initial,
            worker_active=False,
            decomposed_from=event.issue_id,
            depends_on=resolved_depends,
            result_history=[],
        )
        state.issues[real_id] = child

    # Dispatch each child that is not blocked and whose initial state is active
    initial_def = config.states[config.initial]
    if initial_def.worker is not None:
        for _key, real_id in key_to_id.items():
            if not is_blocked(state, config, real_id):
                try_dispatch(config, state, real_id, effects)


def _cascading_unblock(
    config: StateMachineConfig,
    state: State,
    terminal_issue_id: str,
    effects: list[DispatchWorkerEffect],
) -> None:
    terminal_issue = state.issues[terminal_issue_id]

    # 1. Decomposition unblock: if this issue has a parent, check if all siblings are terminal
    if terminal_issue.decomposed_from is not None:
        parent_id = terminal_issue.decomposed_from
        parent = state.issues[parent_id]
        children = get_children(state, parent_id)
        all_terminal = all(config.states[state.issues[cid].state].terminal for cid in children)
        if all_terminal and not parent.worker_active:
            # Parent is no longer decomposition-blocked -> dispatch
            try_dispatch(config, state, parent_id, effects)

    # 2. Dependency unblock: find all issues that depend on the terminal issue
    for iid, iss in state.issues.items():
        if terminal_issue_id in iss.depends_on:
            # Check if all depends_on are now terminal
            all_deps_terminal = all(config.states[state.issues[dep_id].state].terminal for dep_id in iss.depends_on)
            if (
                all_deps_terminal
                and not is_blocked(state, config, iid)
                and not iss.worker_active
                and config.states[iss.state].worker is not None
            ):
                try_dispatch(config, state, iid, effects)
