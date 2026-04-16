from __future__ import annotations

from typing import Any

import yaml

from orca.engine.types import (
    BUILTIN_STATES,
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
    TypeDef,
    WorkerDef,
)

_ALLOWED_WORKER_KINDS = {"claude-code", "opencode"}


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
            then = value.get("then")
            child_type = value.get("child_type")
            return OnDecompose(child_type=child_type, then=then)
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

    max_workers = data.get("max_workers")

    worker: WorkerDef | None = None
    worker_data = data.get("worker")
    if worker_data is not None:
        kind: str = worker_data.get("kind", "")
        prompt: str = worker_data.get("prompt", "")
        timeout: int | None = worker_data.get("timeout")
        inactivity_timeout: int | None = worker_data.get("inactivity_timeout")
        rf_data: dict[str, Any] = worker_data.get("result_format", {})
        result_format: dict[str, ResultFormatField] = {}
        for field_name, field_data in rf_data.items():
            result_format[field_name] = _parse_result_format_field(field_name, field_data)
        model: str | None = worker_data.get("model")
        raw_args = worker_data.get("args")
        args: tuple[str, ...] | None = tuple(str(a) for a in raw_args) if raw_args is not None else None
        progress: bool = bool(worker_data.get("progress", False))
        worker = WorkerDef(
            kind=kind,
            prompt=prompt,
            result_format=result_format,
            timeout=timeout,
            inactivity_timeout=inactivity_timeout,
            model=model,
            args=args,
            progress=progress,
        )

    on: dict[str, OnRule] = {}
    on_data = data.get("True") or data.get("on")
    if on_data is not None:
        for key, value in on_data.items():
            on[key] = _parse_on_rule(key, value)

    return StateDef(
        worker=worker,
        on=on,
        max_workers=max_workers,
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


def _parse_type(name: str, raw: dict[str, Any]) -> TypeDef:
    fields_data = raw.get("fields")
    fields = _parse_issue_fields(fields_data)
    initial = raw.get("initial", "")
    states_data: dict[str, Any] = raw.get("states", {})
    states: dict[str, StateDef] = {}
    for state_name, state_data in states_data.items():
        states[state_name] = _parse_state(state_name, state_data)
    return TypeDef(fields=fields, initial=initial, states=states)


def _validate(config: StateMachineConfig) -> None:
    # Validate max_hops if present
    if config.max_hops is not None and (not isinstance(config.max_hops, int) or config.max_hops < 1):
        msg = f"max_hops must be a positive integer, got {config.max_hops}"
        raise ConfigValidationError(msg)

    # Validate root_type exists in types
    if config.root_type not in config.types:
        msg = f"root_type '{config.root_type}' does not exist in types"
        raise ConfigValidationError(msg)

    all_type_names = set(config.types.keys())

    for type_name, type_def in config.types.items():
        state_names = set(type_def.states.keys())

        # Reserved name check: user must not define done or failed as explicit states
        reserved_in_states = state_names & BUILTIN_STATES
        if reserved_in_states:
            msg = (
                f"Type '{type_name}': states {sorted(reserved_in_states)} are built-in "
                f"and must not be defined explicitly"
            )
            raise ConfigValidationError(msg)

        # Rule 1: initial references an existing state
        if type_def.initial not in state_names:
            msg = f"Type '{type_name}', initial state '{type_def.initial}' does not exist in states"
            raise ConfigValidationError(msg)

        # Collect reachable targets for rule 8
        reachable: set[str] = {type_def.initial}

        for name, state in type_def.states.items():
            # Validate worker fields
            if state.worker is not None:
                if state.worker.kind not in _ALLOWED_WORKER_KINDS:
                    allowed_kinds = sorted(_ALLOWED_WORKER_KINDS)
                    msg = (
                        f"Type '{type_name}', worker for state '{name}': "
                        f"kind must be one of {allowed_kinds}, got '{state.worker.kind}'"
                    )
                    raise ConfigValidationError(msg)
                if not state.worker.prompt:
                    msg = f"Type '{type_name}', worker prompt for state '{name}' must be a non-empty string"
                    raise ConfigValidationError(msg)
                if state.worker.timeout is not None and (
                    not isinstance(state.worker.timeout, int) or state.worker.timeout < 1
                ):
                    msg = (
                        f"Type '{type_name}', worker timeout for state '{name}' "
                        f"must be a positive integer, got {state.worker.timeout}"
                    )
                    raise ConfigValidationError(msg)

            # Rule 9: max_workers must be positive integer
            if state.max_workers is not None and (not isinstance(state.max_workers, int) or state.max_workers < 1):
                msg = (
                    f"Type '{type_name}', max_workers for state '{name}' "
                    f"must be a positive integer, got {state.max_workers}"
                )
                raise ConfigValidationError(msg)

            # Rule 4: active states (with worker+on) must have outcome enum in result_format
            if state.worker is not None and state.on:
                outcome = state.worker.result_format.get("outcome")
                if not isinstance(outcome, EnumFieldDef):
                    msg = f"Type '{type_name}', active state '{name}' must have 'outcome' of type enum in result_format"
                    raise ConfigValidationError(msg)

                # Rule 3: every on key matches a value in outcome.values
                for key in state.on:
                    if key not in outcome.values:
                        msg = (
                            f"Type '{type_name}', on key '{key}' in state '{name}' "
                            f"does not match any outcome value ({outcome.values})"
                        )
                        raise ConfigValidationError(msg)

            # Rule 10: if a state has a worker with an outcome enum, at least one
            # outcome value must have a matching on: rule (state must be able to progress)
            if state.worker is not None:
                outcome_field = state.worker.result_format.get("outcome")
                if isinstance(outcome_field, EnumFieldDef):
                    routable = [v for v in outcome_field.values if v in state.on]
                    if not routable:
                        msg = (
                            f"Type '{type_name}', state '{name}' has no outcome values "
                            f"with matching on: rules — state cannot progress"
                        )
                        raise ConfigValidationError(msg)

            # Rule 2: every on target references an existing state within same type
            # (done and failed are built-in and always valid targets)
            for key, rule in state.on.items():
                if isinstance(rule, OnTransition):
                    if rule.target not in state_names and rule.target not in BUILTIN_STATES:
                        msg = (
                            f"Type '{type_name}', on.{key} target '{rule.target}' in state '{name}' "
                            f"does not exist in states"
                        )
                        raise ConfigValidationError(msg)
                    reachable.add(rule.target)
                elif isinstance(rule, OnDecompose):
                    if rule.child_type is not None and rule.child_type not in all_type_names:
                        msg = f"Type '{type_name}', on.{key} child_type '{rule.child_type}' does not exist in types"
                        raise ConfigValidationError(msg)
                    if rule.then is not None:
                        if rule.then not in state_names and rule.then not in BUILTIN_STATES:
                            msg = (
                                f"Type '{type_name}', on.{key} decompose 'then' target '{rule.then}' "
                                f"in state '{name}' does not exist in states"
                            )
                            raise ConfigValidationError(msg)
                        reachable.add(rule.then)

            # Rule 7: action decompose requires sub_issues with items=$issue
            for _key, rule in state.on.items():
                if isinstance(rule, OnDecompose):
                    if state.worker is None:
                        msg = f"Type '{type_name}', state '{name}' has decompose action but no worker"
                        raise ConfigValidationError(msg)
                    sub = state.worker.result_format.get("sub_issues")
                    if not isinstance(sub, ListFieldDef) or sub.items != "$issue":
                        msg = (
                            f"Type '{type_name}', state '{name}' has action: decompose but result_format "
                            f"is missing 'sub_issues' field with items: $issue"
                        )
                        raise ConfigValidationError(msg)

        # Rule 8: every non-initial, non-passive state must be reachable
        for name, state in type_def.states.items():
            if name in reachable:
                continue
            # Passive states (no worker, no on) are exempt
            is_passive = state.worker is None and not state.on
            if is_passive:
                continue
            msg = f"Type '{type_name}', state '{name}' is not reachable from any on rule"
            raise ConfigValidationError(msg)


def _parse_typed_config(raw: dict[str, Any]) -> StateMachineConfig:
    root_type = raw.get("root_type", "")
    types_data: dict[str, Any] = raw.get("types", {})
    types: dict[str, TypeDef] = {}
    for name, type_data in types_data.items():
        types[name] = _parse_type(name, type_data)
    config = StateMachineConfig(
        root_type=root_type,
        types=types,
    )
    _validate(config)
    return config


def _parse_legacy_config(raw: dict[str, Any]) -> StateMachineConfig:
    issue_data = raw.get("issue", {})
    fields_data = issue_data.get("fields") if isinstance(issue_data, dict) else None
    issue_fields = _parse_issue_fields(fields_data)

    states_data: dict[str, Any] = raw.get("states", {})
    states: dict[str, StateDef] = {}
    for name, state_data in states_data.items():
        states[name] = _parse_state(name, state_data)

    initial: str = raw.get("initial", "")

    # For legacy single-type configs, default decompose child_type to "default"
    for state_def in states.values():
        for key, rule in state_def.on.items():
            if isinstance(rule, OnDecompose) and rule.child_type is None:
                state_def.on[key] = OnDecompose(child_type="default", then=rule.then)

    type_def = TypeDef(fields=issue_fields, initial=initial, states=states)
    config = StateMachineConfig(
        root_type="default",
        types={"default": type_def},
    )
    _validate(config)
    return config


def parse_config(yaml_str: str) -> StateMachineConfig:
    """Parse a YAML string into a StateMachineConfig."""
    raw: Any = yaml.safe_load(yaml_str)
    if not isinstance(raw, dict):
        msg = "Config must be a YAML mapping"
        raise ConfigValidationError(msg)
    if "types" in raw:
        return _parse_typed_config(raw)
    return _parse_legacy_config(raw)
