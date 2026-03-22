from __future__ import annotations

from typing import Any

import yaml

from orca.engine.types import (
    EnumFieldDef,
    FieldDef,
    ListFieldDef,
    OnDecompose,
    OnRule,
    OnTransition,
    ResultFormatField,
    StateDef,
    StateMachineConfig,
    StringFieldDef,
    WorkerDef,
)


class ConfigValidationError(Exception):
    pass


def _parse_required_when(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(v) for v in raw]
    msg = f"required_when must be a string or list, got {type(raw)}"
    raise ConfigValidationError(msg)


def _parse_result_format_field(name: str, data: dict[str, Any]) -> ResultFormatField:
    field_type = data.get("type")
    description = data.get("description", "")

    if field_type == "enum":
        return EnumFieldDef(
            values=data.get("values", []),
            description=description,
            values_description=data.get("values_description", {}),
        )
    elif field_type == "string":
        return StringFieldDef(
            description=description,
            required_when=_parse_required_when(data.get("required_when")),
        )
    elif field_type == "list":
        return ListFieldDef(
            description=description,
            items=data.get("items", ""),
            required_when=_parse_required_when(data.get("required_when")),
        )
    else:
        msg = f"Unknown result_format field type '{field_type}' for field '{name}'"
        raise ConfigValidationError(msg)


def _parse_on_rule(key: str, value: Any) -> OnRule:
    if isinstance(value, str):
        return OnTransition(target=value)
    if isinstance(value, dict):
        action = value.get("action")
        if action == "decompose":
            return OnDecompose()
        msg = f"Unknown action '{action}' in on.{key}"
        raise ConfigValidationError(msg)
    msg = f"Invalid on rule for key '{key}': expected string or dict"
    raise ConfigValidationError(msg)


def _parse_state(name: str, raw_data: dict[str, Any] | None) -> StateDef:
    if raw_data is None:
        raw_data = {}
    # YAML parses bare `on` as boolean True key; normalize to string key
    data: dict[str, Any] = {}
    for k, v in raw_data.items():
        data[str(k)] = v

    terminal = data.get("terminal", False)
    max_workers = data.get("max_workers")

    worker: WorkerDef | None = None
    worker_data = data.get("worker")
    if worker_data is not None:
        kind: str = worker_data.get("kind", "")
        prompt: str = worker_data.get("prompt", "")
        timeout: int | None = worker_data.get("timeout")
        rf_data: dict[str, Any] = worker_data.get("result_format", {})
        result_format: dict[str, ResultFormatField] = {}
        for field_name, field_data in rf_data.items():
            result_format[field_name] = _parse_result_format_field(field_name, field_data)
        worker = WorkerDef(kind=kind, prompt=prompt, result_format=result_format, timeout=timeout)

    on: dict[str, OnRule] = {}
    on_data = data.get("True") or data.get("on")
    if on_data is not None:
        for key, value in on_data.items():
            on[key] = _parse_on_rule(key, value)

    max_visits = data.get("max_visits")

    return StateDef(
        worker=worker,
        on=on,
        terminal=terminal,
        max_workers=max_workers,
        max_visits=max_visits,
    )


def _parse_issue_fields(data: dict[str, Any] | None) -> dict[str, FieldDef]:
    if not data:
        return {}
    result: dict[str, FieldDef] = {}
    for name, field_data in data.items():
        result[name] = FieldDef(
            type=field_data.get("type", ""),
            description=field_data.get("description", ""),
        )
    return result


def _validate(config: StateMachineConfig) -> None:
    state_names = set(config.states.keys())

    # Validate max_hops if present
    if config.max_hops is not None and (not isinstance(config.max_hops, int) or config.max_hops < 1):
        msg = f"max_hops must be a positive integer, got {config.max_hops}"
        raise ConfigValidationError(msg)

    # Rule 1: initial references an existing state
    if config.initial not in state_names:
        msg = f"initial state '{config.initial}' does not reference an existing state"
        raise ConfigValidationError(msg)

    # Rule 6: at least one terminal state
    terminal_states = {name for name, s in config.states.items() if s.terminal}
    if not terminal_states:
        msg = "At least one terminal state is required"
        raise ConfigValidationError(msg)

    # Collect reachable targets for rule 8
    reachable: set[str] = {config.initial}

    for name, state in config.states.items():
        # Validate worker fields
        if state.worker is not None:
            if state.worker.kind != "claude-code":
                msg = f"Worker for state '{name}': kind must be 'claude-code', got '{state.worker.kind}'"
                raise ConfigValidationError(msg)
            if not state.worker.prompt:
                msg = f"Worker prompt for state '{name}' must be a non-empty string"
                raise ConfigValidationError(msg)
            if state.worker.timeout is not None and (
                not isinstance(state.worker.timeout, int) or state.worker.timeout < 1
            ):
                msg = f"Worker timeout for state '{name}' must be a positive integer, got {state.worker.timeout}"
                raise ConfigValidationError(msg)

        # Rule 9: max_workers must be positive integer
        if state.max_workers is not None and (not isinstance(state.max_workers, int) or state.max_workers < 1):
            msg = f"max_workers for state '{name}' must be a positive integer, got {state.max_workers}"
            raise ConfigValidationError(msg)

        # max_visits must be positive integer
        if state.max_visits is not None and (not isinstance(state.max_visits, int) or state.max_visits < 1):
            msg = f"max_visits for state '{name}' must be a positive integer, got {state.max_visits}"
            raise ConfigValidationError(msg)

        # Rule 5: terminal states have no worker or on
        if state.terminal:
            if state.worker is not None or state.on:
                msg = f"Terminal state '{name}' must not have worker or on rules"
                raise ConfigValidationError(msg)
            continue

        # Rule 4: active states (with worker+on) must have outcome enum in result_format
        if state.worker is not None and state.on:
            outcome = state.worker.result_format.get("outcome")
            if not isinstance(outcome, EnumFieldDef):
                msg = f"Active state '{name}' must have 'outcome' of type enum in result_format"
                raise ConfigValidationError(msg)

            # Rule 3: every on key matches a value in outcome.values
            for key in state.on:
                if key not in outcome.values:
                    msg = f"on key '{key}' in state '{name}' does not match any outcome value ({outcome.values})"
                    raise ConfigValidationError(msg)

        # Rule 2: every on target references an existing state
        for key, rule in state.on.items():
            if isinstance(rule, OnTransition):
                if rule.target not in state_names:
                    msg = f"on.{key} target '{rule.target}' in state '{name}' does not reference an existing state"
                    raise ConfigValidationError(msg)
                reachable.add(rule.target)

        # Rule 7: action decompose requires sub_issues with items=$issue
        for _key, rule in state.on.items():
            if isinstance(rule, OnDecompose):
                if state.worker is None:
                    msg = f"State '{name}' has decompose action but no worker"
                    raise ConfigValidationError(msg)
                sub = state.worker.result_format.get("sub_issues")
                if not isinstance(sub, ListFieldDef) or sub.items != "$issue":
                    msg = (
                        f"State '{name}' has action: decompose but result_format is missing "
                        f"'sub_issues' field with items: $issue"
                    )
                    raise ConfigValidationError(msg)

    # Rule 8: every non-initial, non-passive state must be reachable
    for name, state in config.states.items():
        if name in reachable:
            continue
        # Passive states (no worker, no on, not terminal) are exempt
        is_passive = state.worker is None and not state.on and not state.terminal
        if is_passive:
            continue
        msg = f"State '{name}' is not reachable from any on rule"
        raise ConfigValidationError(msg)


def parse_config(yaml_str: str) -> StateMachineConfig:
    """Parse a YAML string into a StateMachineConfig."""
    raw: Any = yaml.safe_load(yaml_str)
    if not isinstance(raw, dict):
        msg = "Config must be a YAML mapping"
        raise ConfigValidationError(msg)

    # Parse issue fields
    issue_data = raw.get("issue", {})
    fields_data = issue_data.get("fields") if isinstance(issue_data, dict) else None
    issue_fields = _parse_issue_fields(fields_data)

    # Parse states
    states_data: dict[str, Any] = raw.get("states", {})
    states: dict[str, StateDef] = {}
    for name, state_data in states_data.items():
        states[name] = _parse_state(name, state_data)

    initial: str = raw.get("initial", "")
    max_hops = raw.get("max_hops")

    config = StateMachineConfig(
        issue_fields=issue_fields,
        initial=initial,
        states=states,
        max_hops=max_hops,
    )

    _validate(config)

    return config
