from __future__ import annotations

import copy
from collections.abc import Callable

from orca.engine.dispatch import is_blocked, try_dispatch
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    Effect,
    ErrorEffect,
    Event,
    Issue,
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
    elif isinstance(event, WorkerResultEvent | WorkerFailedEvent):
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
