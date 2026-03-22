# State Machine Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a pure reducer function that drives issue lifecycle through a user-defined state machine configured via `orca.yml`.

**Architecture:** The engine is a pure function `reduce(config, state, event, generate_id) -> (new_state, effects)`. Config is parsed from YAML into typed dataclasses. State and events are typed dataclasses serializable to/from JSON. The reducer has no I/O — all side effects are returned as data objects.

**Tech Stack:** Python 3.12, dataclasses, PyYAML, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-state-machine-engine-design.md`

---

## File Structure

```
src/orca/
├── __init__.py                  (existing)
├── py.typed                     (existing)
├── engine/
│   ├── __init__.py              — public API re-exports
│   ├── types.py                 — all dataclasses: Config, State, Event, Effect, Issue
│   ├── config.py                — YAML parsing + validation
│   ├── reducer.py               — pure reduce() function
│   └── dispatch.py              — dispatch protocol (max_workers, queuing)
tests/
├── __init__.py
├── engine/
│   ├── __init__.py
│   ├── test_types.py            — serialization round-trips
│   ├── test_config.py           — YAML parsing + validation rules
│   ├── test_reducer_create.py   — Create event handling
│   ├── test_reducer_advance.py  — Advance event handling
│   ├── test_reducer_worker_result.py — WorkerResult: transitions, decompose, unblock
│   ├── test_reducer_worker_failed.py — WorkerFailed event handling
│   ├── test_dispatch.py         — max_workers, queuing, slot backfill
│   └── conftest.py              — shared fixtures: sample configs, states, helper functions
```

---

### Task 1: Project Setup — Add pytest and pyyaml Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies**

```bash
uv add --dev pytest
uv add pyyaml
```

- [ ] **Step 2: Verify pytest runs**

Run: `uv run pytest --co -q`
Expected: "no tests ran" (no test files yet)

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p src/orca/engine tests/engine
touch src/orca/engine/__init__.py tests/__init__.py tests/engine/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock src/orca/engine/__init__.py tests/__init__.py tests/engine/__init__.py
git commit -m "chore: add pytest, pyyaml, create engine and tests directories"
```

---

### Task 2: Core Types — Dataclasses for Config, State, Events, Effects

**Files:**
- Create: `src/orca/engine/types.py`
- Create: `tests/engine/test_types.py`

- [ ] **Step 1: Write the failing test for type construction and serialization**

```python
# tests/engine/test_types.py
import json
from orca.engine.types import (
    Issue,
    State,
    CreateEvent,
    AdvanceEvent,
    WorkerResultEvent,
    WorkerFailedEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    FieldDef,
    EnumFieldDef,
    StringFieldDef,
    ListFieldDef,
    StateDef,
    WorkerDef,
    OnTransition,
    OnDecompose,
    StateMachineConfig,
    ResultHistoryEntry,
)


def test_issue_construction() -> None:
    issue = Issue(
        fields={"title": "Test", "text": "Description"},
        state="todo",
        blocked=False,
        worker_active=False,
        parent=None,
        children=[],
        result_history=[],
    )
    assert issue.state == "todo"
    assert issue.blocked is False
    assert issue.worker_active is False


def test_state_serialization_roundtrip() -> None:
    state = State(
        issues={
            "ISSUE-1": Issue(
                fields={"title": "Test"},
                state="todo",
                blocked=False,
                worker_active=False,
                parent=None,
                children=[],
                result_history=[],
            )
        },
        worker_queues={},
    )
    data = state.to_dict()
    json_str = json.dumps(data)
    restored = State.from_dict(json.loads(json_str))
    assert restored.issues["ISSUE-1"].fields == {"title": "Test"}
    assert restored.issues["ISSUE-1"].state == "todo"
    assert restored.worker_queues == {}


def test_state_with_result_history_roundtrip() -> None:
    entry = ResultHistoryEntry(state="implementing", result={"outcome": "done", "summary": "Built it"})
    issue = Issue(
        fields={"title": "Test"},
        state="done",
        blocked=False,
        worker_active=False,
        parent="PARENT-1",
        children=[],
        result_history=[entry],
    )
    state = State(issues={"ISSUE-1": issue}, worker_queues={})
    data = state.to_dict()
    restored = State.from_dict(data)
    assert len(restored.issues["ISSUE-1"].result_history) == 1
    assert restored.issues["ISSUE-1"].result_history[0].state == "implementing"
    assert restored.issues["ISSUE-1"].result_history[0].result["outcome"] == "done"


def test_state_with_worker_queues_roundtrip() -> None:
    state = State(
        issues={},
        worker_queues={"apply": ["ISSUE-2", "ISSUE-3"]},
    )
    data = state.to_dict()
    restored = State.from_dict(data)
    assert restored.worker_queues == {"apply": ["ISSUE-2", "ISSUE-3"]}


def test_create_event() -> None:
    event = CreateEvent(issue_id="ISSUE-1", fields={"title": "Test"})
    assert event.issue_id == "ISSUE-1"


def test_advance_event() -> None:
    event = AdvanceEvent(issue_id="ISSUE-1", target_state="implementing")
    assert event.target_state == "implementing"


def test_worker_result_event() -> None:
    event = WorkerResultEvent(issue_id="ISSUE-1", result={"outcome": "done"})
    assert event.result["outcome"] == "done"


def test_worker_failed_event() -> None:
    event = WorkerFailedEvent(issue_id="ISSUE-1", error="timeout")
    assert event.error == "timeout"


def test_dispatch_worker_effect() -> None:
    effect = DispatchWorkerEffect(
        issue_id="ISSUE-1",
        state="implementing",
        result_format={"outcome": {"type": "enum", "values": ["done"]}},
        issue={"fields": {"title": "Test"}, "result_history": [], "parent": None, "children": []},
    )
    assert effect.state == "implementing"


def test_error_effect() -> None:
    effect = ErrorEffect(issue_id="ISSUE-1", message="blocked")
    assert effect.message == "blocked"


def test_config_types() -> None:
    enum_field = EnumFieldDef(
        values=["ready", "decompose"],
        description="outcome",
        values_description={"ready": "ready", "decompose": "split"},
    )
    assert enum_field.values == ["ready", "decompose"]

    string_field = StringFieldDef(description="summary")
    assert string_field.description == "summary"

    list_field = ListFieldDef(description="sub-issues", items="$issue", required_when=["decompose"])
    assert list_field.items == "$issue"

    worker = WorkerDef(result_format={"outcome": enum_field, "summary": string_field})
    assert "outcome" in worker.result_format

    on_transition = OnTransition(target="implementing")
    assert on_transition.target == "implementing"

    on_decompose = OnDecompose()
    assert isinstance(on_decompose, OnDecompose)

    state_def = StateDef(worker=worker, on={"ready": on_transition, "decompose": on_decompose})
    assert state_def.worker is not None

    passive_def = StateDef()
    assert passive_def.worker is None
    assert passive_def.terminal is False

    terminal_def = StateDef(terminal=True)
    assert terminal_def.terminal is True

    field_def = FieldDef(type="string", description="title")
    config = StateMachineConfig(
        issue_fields={"title": field_def},
        initial="todo",
        states={"todo": passive_def, "implementing": state_def, "done": terminal_def},
    )
    assert config.initial == "todo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_types.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement types**

```python
# src/orca/engine/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- Config types ---


@dataclass(frozen=True)
class FieldDef:
    type: str
    description: str


@dataclass(frozen=True)
class EnumFieldDef:
    values: list[str]
    description: str
    values_description: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StringFieldDef:
    description: str
    required_when: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ListFieldDef:
    description: str
    items: str
    required_when: list[str] = field(default_factory=list)


ResultFormatField = EnumFieldDef | StringFieldDef | ListFieldDef


@dataclass(frozen=True)
class WorkerDef:
    result_format: dict[str, ResultFormatField]


@dataclass(frozen=True)
class OnTransition:
    target: str


@dataclass(frozen=True)
class OnDecompose:
    pass


OnRule = OnTransition | OnDecompose


@dataclass(frozen=True)
class StateDef:
    worker: WorkerDef | None = None
    on: dict[str, OnRule] = field(default_factory=dict)
    terminal: bool = False
    max_workers: int | None = None


@dataclass(frozen=True)
class StateMachineConfig:
    issue_fields: dict[str, FieldDef]
    initial: str
    states: dict[str, StateDef]


# --- Runtime state types ---


@dataclass
class ResultHistoryEntry:
    state: str
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "result": self.result}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResultHistoryEntry:
        return cls(state=data["state"], result=data["result"])


@dataclass
class Issue:
    fields: dict[str, Any]
    state: str
    blocked: bool
    worker_active: bool
    parent: str | None
    children: list[str]
    result_history: list[ResultHistoryEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "state": self.state,
            "blocked": self.blocked,
            "worker_active": self.worker_active,
            "parent": self.parent,
            "children": self.children,
            "result_history": [e.to_dict() for e in self.result_history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Issue:
        return cls(
            fields=data["fields"],
            state=data["state"],
            blocked=data["blocked"],
            worker_active=data["worker_active"],
            parent=data["parent"],
            children=data["children"],
            result_history=[ResultHistoryEntry.from_dict(e) for e in data["result_history"]],
        )


@dataclass
class State:
    issues: dict[str, Issue]
    worker_queues: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": {k: v.to_dict() for k, v in self.issues.items()},
            "worker_queues": self.worker_queues,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        return cls(
            issues={k: Issue.from_dict(v) for k, v in data["issues"].items()},
            worker_queues=data.get("worker_queues", {}),
        )


# --- Events ---


@dataclass(frozen=True)
class CreateEvent:
    issue_id: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class AdvanceEvent:
    issue_id: str
    target_state: str


@dataclass(frozen=True)
class WorkerResultEvent:
    issue_id: str
    result: dict[str, Any]


@dataclass(frozen=True)
class WorkerFailedEvent:
    issue_id: str
    error: str


Event = CreateEvent | AdvanceEvent | WorkerResultEvent | WorkerFailedEvent


# --- Effects ---


@dataclass(frozen=True)
class DispatchWorkerEffect:
    issue_id: str
    state: str
    result_format: dict[str, Any]
    issue: dict[str, Any]


@dataclass(frozen=True)
class ErrorEffect:
    issue_id: str
    message: str


Effect = DispatchWorkerEffect | ErrorEffect
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_types.py -v`
Expected: all PASS

- [ ] **Step 5: Run ruff and mypy**

Run: `uv run ruff check src/orca/engine/types.py tests/engine/test_types.py && uv run mypy src/orca/engine/types.py tests/engine/test_types.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/types.py tests/engine/test_types.py
git commit -m "feat: add core type definitions for state machine engine"
```

---

### Task 3: Config Parsing — YAML to StateMachineConfig

**Files:**
- Create: `src/orca/engine/config.py`
- Create: `tests/engine/test_config.py`
- Create: `tests/engine/conftest.py`

- [ ] **Step 1: Write conftest with shared YAML fixtures**

```python
# tests/engine/conftest.py
import pytest


SIMPLE_CONFIG_YAML = """\
issue:
  fields:
    title:
      type: string
      description: "Short title"
    text:
      type: string
      description: "Description"

initial: todo

states:
  todo: {}

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Result"
          values_description:
            done: "Complete"
        summary:
          type: string
          description: "Summary"
    on:
      done: done

  done:
    terminal: true
"""

DECOMPOSE_CONFIG_YAML = """\
issue:
  fields:
    title:
      type: string
      description: "Title"
    text:
      type: string
      description: "Text"

initial: todo

states:
  todo: {}

  scoping:
    worker:
      result_format:
        outcome:
          type: enum
          values: [ready, decompose]
          description: "Scope result"
          values_description:
            ready: "Ready"
            decompose: "Needs split"
        sub_issues:
          type: list
          required_when: decompose
          items: $issue
          description: "Sub-issues"
    on:
      ready: implementing
      decompose:
        action: decompose

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Result"
          values_description:
            done: "Complete"
    on:
      done: done

  done:
    terminal: true
"""

MAX_WORKERS_CONFIG_YAML = """\
issue:
  fields:
    title:
      type: string
      description: "Title"

initial: todo

states:
  todo: {}

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Result"
          values_description:
            done: "Complete"
    on:
      done: apply

  apply:
    max_workers: 1
    worker:
      result_format:
        outcome:
          type: enum
          values: [merged, conflict]
          description: "Merge result"
          values_description:
            merged: "Merged"
            conflict: "Conflict"
    on:
      merged: done
      conflict: implementing

  done:
    terminal: true
"""


@pytest.fixture
def simple_config_yaml() -> str:
    return SIMPLE_CONFIG_YAML


@pytest.fixture
def decompose_config_yaml() -> str:
    return DECOMPOSE_CONFIG_YAML


@pytest.fixture
def max_workers_config_yaml() -> str:
    return MAX_WORKERS_CONFIG_YAML
```

- [ ] **Step 2: Write failing tests for config parsing and validation**

```python
# tests/engine/test_config.py
import pytest
from orca.engine.config import parse_config, ConfigValidationError
from orca.engine.types import OnTransition, OnDecompose, EnumFieldDef, StringFieldDef, ListFieldDef


def test_parse_simple_config(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    assert config.initial == "todo"
    assert "todo" in config.states
    assert "implementing" in config.states
    assert "done" in config.states
    assert config.states["done"].terminal is True
    assert config.states["todo"].worker is None
    assert config.states["implementing"].worker is not None
    worker = config.states["implementing"].worker
    assert isinstance(worker.result_format["outcome"], EnumFieldDef)
    assert isinstance(worker.result_format["summary"], StringFieldDef)
    on = config.states["implementing"].on
    assert isinstance(on["done"], OnTransition)
    assert on["done"].target == "done"


def test_parse_decompose_config(decompose_config_yaml: str) -> None:
    config = parse_config(decompose_config_yaml)
    scoping = config.states["scoping"]
    assert scoping.worker is not None
    assert isinstance(scoping.on["decompose"], OnDecompose)
    assert isinstance(scoping.on["ready"], OnTransition)
    sub_issues_field = scoping.worker.result_format["sub_issues"]
    assert isinstance(sub_issues_field, ListFieldDef)
    assert sub_issues_field.items == "$issue"
    assert sub_issues_field.required_when == ["decompose"]


def test_parse_max_workers_config(max_workers_config_yaml: str) -> None:
    config = parse_config(max_workers_config_yaml)
    assert config.states["apply"].max_workers == 1
    assert config.states["implementing"].max_workers is None


def test_issue_fields_parsed(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    assert "title" in config.issue_fields
    assert config.issue_fields["title"].type == "string"


def test_validation_initial_references_existing_state() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: nonexistent
states:
  todo: {}
  done:
    terminal: true
"""
    with pytest.raises(ConfigValidationError, match="initial.*nonexistent"):
        parse_config(yaml_str)


def test_validation_on_target_references_existing_state() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: todo
states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "r"
    on:
      done: nonexistent
  done:
    terminal: true
"""
    with pytest.raises(ConfigValidationError, match="nonexistent"):
        parse_config(yaml_str)


def test_validation_on_key_matches_outcome_values() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: work
states:
  work:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "r"
    on:
      invalid_key: done
  done:
    terminal: true
"""
    with pytest.raises(ConfigValidationError, match="invalid_key"):
        parse_config(yaml_str)


def test_validation_active_state_requires_outcome() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: work
states:
  work:
    worker:
      result_format:
        summary:
          type: string
          description: "s"
    on:
      done: done
  done:
    terminal: true
"""
    with pytest.raises(ConfigValidationError, match="outcome"):
        parse_config(yaml_str)


def test_validation_terminal_state_no_worker() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: todo
states:
  todo: {}
  done:
    terminal: true
    worker:
      result_format:
        outcome:
          type: enum
          values: [x]
          description: "r"
    on:
      x: todo
"""
    with pytest.raises(ConfigValidationError, match="terminal.*worker"):
        parse_config(yaml_str)


def test_validation_at_least_one_terminal() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: todo
states:
  todo: {}
"""
    with pytest.raises(ConfigValidationError, match="terminal"):
        parse_config(yaml_str)


def test_validation_decompose_requires_sub_issues() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: work
states:
  work:
    worker:
      result_format:
        outcome:
          type: enum
          values: [ready, decompose]
          description: "r"
    on:
      ready: done
      decompose:
        action: decompose
  done:
    terminal: true
"""
    with pytest.raises(ConfigValidationError, match="sub_issues"):
        parse_config(yaml_str)


def test_validation_max_workers_positive() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: work
states:
  work:
    max_workers: 0
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "r"
    on:
      done: done
  done:
    terminal: true
"""
    with pytest.raises(ConfigValidationError, match="max_workers.*positive"):
        parse_config(yaml_str)


def test_validation_required_when_as_string(decompose_config_yaml: str) -> None:
    """required_when should be normalized to a list even when given as a string."""
    config = parse_config(decompose_config_yaml)
    sub_issues = config.states["scoping"].worker.result_format["sub_issues"]
    assert isinstance(sub_issues, ListFieldDef)
    assert sub_issues.required_when == ["decompose"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_config.py -v`
Expected: FAIL with ImportError

- [ ] **Step 4: Implement config parsing**

```python
# src/orca/engine/config.py
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


def parse_config(yaml_str: str) -> StateMachineConfig:
    raw = yaml.safe_load(yaml_str)
    issue_fields = _parse_issue_fields(raw["issue"]["fields"])
    initial = raw["initial"]
    states = {name: _parse_state_def(name, data) for name, data in raw["states"].items()}
    config = StateMachineConfig(issue_fields=issue_fields, initial=initial, states=states)
    _validate(config)
    return config


def _parse_issue_fields(raw: dict[str, Any]) -> dict[str, FieldDef]:
    return {name: FieldDef(type=data["type"], description=data["description"]) for name, data in raw.items()}


def _parse_state_def(name: str, data: Any) -> StateDef:
    if data is None:
        data = {}
    if isinstance(data, dict) and data.get("terminal"):
        if "worker" in data or "on" in data:
            raise ConfigValidationError(f"State '{name}': terminal state cannot have worker or on")
        return StateDef(terminal=True)
    if "worker" not in data:
        return StateDef()
    worker = _parse_worker_def(data["worker"])
    on = _parse_on_rules(data.get("on", {}))
    max_workers = data.get("max_workers")
    return StateDef(worker=worker, on=on, max_workers=max_workers)


def _parse_worker_def(raw: dict[str, Any]) -> WorkerDef:
    result_format: dict[str, ResultFormatField] = {}
    for field_name, field_data in raw["result_format"].items():
        result_format[field_name] = _parse_result_format_field(field_data)
    return WorkerDef(result_format=result_format)


def _parse_result_format_field(data: dict[str, Any]) -> ResultFormatField:
    field_type = data["type"]
    required_when_raw = data.get("required_when")
    required_when: list[str] = []
    if isinstance(required_when_raw, str):
        required_when = [required_when_raw]
    elif isinstance(required_when_raw, list):
        required_when = required_when_raw

    if field_type == "enum":
        return EnumFieldDef(
            values=data["values"],
            description=data["description"],
            values_description=data.get("values_description", {}),
        )
    elif field_type == "string":
        return StringFieldDef(description=data["description"], required_when=required_when)
    elif field_type == "list":
        return ListFieldDef(
            description=data["description"],
            items=data["items"],
            required_when=required_when,
        )
    else:
        raise ConfigValidationError(f"Unknown field type: {field_type}")


def _parse_on_rules(raw: dict[str, Any]) -> dict[str, OnRule]:
    rules: dict[str, OnRule] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            rules[key] = OnTransition(target=value)
        elif isinstance(value, dict) and value.get("action") == "decompose":
            rules[key] = OnDecompose()
        else:
            raise ConfigValidationError(f"Invalid on rule for '{key}': {value}")
    return rules


def _validate(config: StateMachineConfig) -> None:
    # Rule 1: initial references existing state
    if config.initial not in config.states:
        raise ConfigValidationError(f"initial state '{config.initial}' does not exist in states")

    # Rule 6: at least one terminal
    terminal_states = [name for name, s in config.states.items() if s.terminal]
    if not terminal_states:
        raise ConfigValidationError("At least one terminal state must exist")

    for name, state_def in config.states.items():
        if state_def.terminal:
            # Rule 5: terminal has no worker or on
            if state_def.worker is not None or state_def.on:
                raise ConfigValidationError(f"State '{name}': terminal state cannot have worker or on")
            continue

        if state_def.worker is None:
            # Passive state
            continue

        # Rule 4: active state must have outcome enum
        if "outcome" not in state_def.worker.result_format:
            raise ConfigValidationError(f"State '{name}': active state must have 'outcome' in result_format")
        outcome_field = state_def.worker.result_format["outcome"]
        if not isinstance(outcome_field, EnumFieldDef):
            raise ConfigValidationError(f"State '{name}': 'outcome' must be of type enum")

        outcome_values = outcome_field.values

        for on_key, on_rule in state_def.on.items():
            # Rule 3: on key matches outcome values
            if on_key not in outcome_values:
                raise ConfigValidationError(
                    f"State '{name}': on key '{on_key}' not in outcome values {outcome_values}"
                )
            # Rule 2: on target references existing state
            if isinstance(on_rule, OnTransition) and on_rule.target not in config.states:
                raise ConfigValidationError(
                    f"State '{name}': on target '{on_rule.target}' does not exist in states"
                )
            # Rule 7: decompose requires sub_issues with items: $issue
            if isinstance(on_rule, OnDecompose):
                has_sub_issues = False
                for rf_name, rf_field in state_def.worker.result_format.items():
                    if rf_name == "sub_issues" and isinstance(rf_field, ListFieldDef) and rf_field.items == "$issue":
                        has_sub_issues = True
                        break
                if not has_sub_issues:
                    raise ConfigValidationError(
                        f"State '{name}': action decompose requires 'sub_issues' field with items: $issue"
                    )

        # Rule 9: max_workers positive
        if state_def.max_workers is not None and state_def.max_workers < 1:
            raise ConfigValidationError(f"State '{name}': max_workers must be a positive integer")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_config.py -v`
Expected: all PASS

- [ ] **Step 6: Run ruff and mypy**

Run: `uv run ruff check src/orca/engine/config.py tests/engine/test_config.py && uv run mypy src/orca/engine/config.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/engine/config.py tests/engine/test_config.py tests/engine/conftest.py
git commit -m "feat: add config parsing and validation for orca.yml"
```

---

### Task 4: Dispatch Protocol — max_workers and Queuing Logic

**Files:**
- Create: `src/orca/engine/dispatch.py`
- Create: `tests/engine/test_dispatch.py`

- [ ] **Step 1: Write failing tests for dispatch protocol**

```python
# tests/engine/test_dispatch.py
from orca.engine.types import (
    Issue,
    State,
    StateDef,
    WorkerDef,
    EnumFieldDef,
    StateMachineConfig,
    FieldDef,
    DispatchWorkerEffect,
)
from orca.engine.dispatch import try_dispatch, backfill_queue


def _make_config(max_workers: int | None = None) -> StateMachineConfig:
    return StateMachineConfig(
        issue_fields={"title": FieldDef(type="string", description="t")},
        initial="todo",
        states={
            "todo": StateDef(),
            "work": StateDef(
                max_workers=max_workers,
                worker=WorkerDef(
                    result_format={
                        "outcome": EnumFieldDef(values=["done"], description="r", values_description={"done": "d"})
                    }
                ),
                on={},
            ),
            "done": StateDef(terminal=True),
        },
    )


def _make_issue(state: str, worker_active: bool = False) -> Issue:
    return Issue(
        fields={"title": "test"},
        state=state,
        blocked=False,
        worker_active=worker_active,
        parent=None,
        children=[],
        result_history=[],
    )


def test_dispatch_no_limit() -> None:
    config = _make_config(max_workers=None)
    state = State(issues={"I-1": _make_issue("work")}, worker_queues={})
    effects: list[DispatchWorkerEffect] = []
    try_dispatch(config, state, "I-1", effects)
    assert len(effects) == 1
    assert state.issues["I-1"].worker_active is True


def test_dispatch_under_limit() -> None:
    config = _make_config(max_workers=2)
    state = State(issues={"I-1": _make_issue("work"), "I-2": _make_issue("work")}, worker_queues={})
    effects: list[DispatchWorkerEffect] = []
    try_dispatch(config, state, "I-1", effects)
    assert len(effects) == 1
    assert state.issues["I-1"].worker_active is True


def test_dispatch_at_limit_queues() -> None:
    config = _make_config(max_workers=1)
    i1 = _make_issue("work", worker_active=True)
    i2 = _make_issue("work")
    state = State(issues={"I-1": i1, "I-2": i2}, worker_queues={})
    effects: list[DispatchWorkerEffect] = []
    try_dispatch(config, state, "I-2", effects)
    assert len(effects) == 0
    assert state.issues["I-2"].worker_active is False
    assert state.worker_queues["work"] == ["I-2"]


def test_backfill_dispatches_next_in_queue() -> None:
    config = _make_config(max_workers=1)
    i1 = _make_issue("work", worker_active=False)  # just finished
    i2 = _make_issue("work")
    i3 = _make_issue("work")
    state = State(issues={"I-1": i1, "I-2": i2, "I-3": i3}, worker_queues={"work": ["I-2", "I-3"]})
    effects: list[DispatchWorkerEffect] = []
    backfill_queue(config, state, "work", effects)
    assert len(effects) == 1
    assert effects[0].issue_id == "I-2"
    assert state.issues["I-2"].worker_active is True
    assert state.worker_queues["work"] == ["I-3"]


def test_backfill_skips_blocked() -> None:
    config = _make_config(max_workers=1)
    i1 = _make_issue("work")
    i1.blocked = True
    i2 = _make_issue("work")
    state = State(issues={"I-1": i1, "I-2": i2}, worker_queues={"work": ["I-1", "I-2"]})
    effects: list[DispatchWorkerEffect] = []
    backfill_queue(config, state, "work", effects)
    assert len(effects) == 1
    assert effects[0].issue_id == "I-2"


def test_dispatch_includes_resolved_children() -> None:
    config = _make_config(max_workers=None)
    parent = _make_issue("work")
    parent.children = ["I-2"]
    child = _make_issue("done")
    child.parent = "I-1"
    child.result_history = []
    state = State(issues={"I-1": parent, "I-2": child}, worker_queues={})
    effects: list[DispatchWorkerEffect] = []
    try_dispatch(config, state, "I-1", effects)
    assert len(effects) == 1
    children_data = effects[0].issue["children"]
    assert len(children_data) == 1
    assert children_data[0]["issue_id"] == "I-2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_dispatch.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement dispatch protocol**

```python
# src/orca/engine/dispatch.py
from __future__ import annotations

from typing import Any

from orca.engine.types import (
    DispatchWorkerEffect,
    EnumFieldDef,
    Issue,
    ListFieldDef,
    State,
    StateMachineConfig,
    StringFieldDef,
)


def build_issue_context(state: State, issue_id: str) -> dict[str, Any]:
    issue = state.issues[issue_id]
    children_data: list[dict[str, Any]] = []
    for child_id in issue.children:
        child = state.issues[child_id]
        children_data.append(
            {
                "issue_id": child_id,
                "fields": child.fields,
                "state": child.state,
                "result_history": [e.to_dict() for e in child.result_history],
            }
        )
    return {
        "fields": issue.fields,
        "result_history": [e.to_dict() for e in issue.result_history],
        "parent": issue.parent,
        "children": children_data,
    }


def build_result_format(config: StateMachineConfig, state_name: str) -> dict[str, Any]:
    state_def = config.states[state_name]
    assert state_def.worker is not None
    result: dict[str, Any] = {}
    for name, field in state_def.worker.result_format.items():
        if isinstance(field, EnumFieldDef):
            entry: dict[str, Any] = {
                "type": "enum",
                "values": field.values,
                "description": field.description,
            }
            if field.values_description:
                entry["values_description"] = field.values_description
            result[name] = entry
        elif isinstance(field, ListFieldDef):
            result[name] = {"type": "list", "description": field.description, "items": field.items}
        elif isinstance(field, StringFieldDef):
            result[name] = {"type": "string", "description": field.description}
    return result


def count_active_workers(state: State, state_name: str) -> int:
    return sum(1 for issue in state.issues.values() if issue.state == state_name and issue.worker_active)


def try_dispatch(
    config: StateMachineConfig,
    state: State,
    issue_id: str,
    effects: list[DispatchWorkerEffect],
) -> None:
    issue = state.issues[issue_id]
    state_name = issue.state
    state_def = config.states[state_name]

    if state_def.worker is None:
        return

    max_w = state_def.max_workers
    if max_w is not None and count_active_workers(state, state_name) >= max_w:
        # Queue the issue
        if state_name not in state.worker_queues:
            state.worker_queues[state_name] = []
        if issue_id not in state.worker_queues[state_name]:
            state.worker_queues[state_name].append(issue_id)
        return

    issue.worker_active = True
    effects.append(
        DispatchWorkerEffect(
            issue_id=issue_id,
            state=state_name,
            result_format=_build_result_format(config, state_name),
            issue=_build_issue_context(state, issue_id),
        )
    )


def backfill_queue(
    config: StateMachineConfig,
    state: State,
    state_name: str,
    effects: list[DispatchWorkerEffect],
) -> None:
    if state_name not in state.worker_queues:
        return
    queue = state.worker_queues[state_name]
    while queue:
        candidate_id = queue[0]
        if candidate_id not in state.issues:
            queue.pop(0)
            continue
        candidate = state.issues[candidate_id]
        if candidate.blocked or candidate.state != state_name:
            queue.pop(0)
            continue
        queue.pop(0)
        try_dispatch(config, state, candidate_id, effects)
        return
    # Clean up empty queue
    if not queue:
        del state.worker_queues[state_name]


def remove_from_queue(state: State, state_name: str, issue_id: str) -> None:
    if state_name in state.worker_queues and issue_id in state.worker_queues[state_name]:
        state.worker_queues[state_name].remove(issue_id)
        if not state.worker_queues[state_name]:
            del state.worker_queues[state_name]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_dispatch.py -v`
Expected: all PASS

- [ ] **Step 5: Run ruff and mypy**

Run: `uv run ruff check src/orca/engine/dispatch.py tests/engine/test_dispatch.py && uv run mypy src/orca/engine/dispatch.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/dispatch.py tests/engine/test_dispatch.py
git commit -m "feat: add dispatch protocol with max_workers and queuing"
```

---

### Task 5: Reducer — Create Event

**Files:**
- Create: `src/orca/engine/reducer.py`
- Create: `tests/engine/test_reducer_create.py`

- [ ] **Step 1: Write failing tests for Create event**

```python
# tests/engine/test_reducer_create.py
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
)
from orca.engine.reducer import reduce


def _counter() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def test_create_issue_in_passive_initial(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    state = State(issues={}, worker_queues={})
    event = CreateEvent(issue_id="I-1", fields={"title": "Test", "text": "Desc"})
    new_state, effects = reduce(config, state, event, _counter())
    assert "I-1" in new_state.issues
    issue = new_state.issues["I-1"]
    assert issue.state == "todo"
    assert issue.blocked is False
    assert issue.worker_active is False
    assert issue.parent is None
    assert issue.children == []
    assert issue.result_history == []
    assert issue.fields == {"title": "Test", "text": "Desc"}
    # Passive initial state — no dispatch
    assert len(effects) == 0


def test_create_issue_in_active_initial() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
initial: work
states:
  work:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "r"
          values_description:
            done: "d"
    on:
      done: done
  done:
    terminal: true
"""
    config = parse_config(yaml_str)
    state = State(issues={}, worker_queues={})
    event = CreateEvent(issue_id="I-1", fields={"title": "Test"})
    new_state, effects = reduce(config, state, event, _counter())
    assert new_state.issues["I-1"].worker_active is True
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
    assert len(dispatch_effects) == 1
    assert dispatch_effects[0].issue_id == "I-1"


def test_create_duplicate_issue_id(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    state = State(issues={}, worker_queues={})
    event = CreateEvent(issue_id="I-1", fields={"title": "Test", "text": "Desc"})
    state, _ = reduce(config, state, event, _counter())
    # Try to create again with same ID
    state2, effects = reduce(config, state, event, _counter())
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
    assert "already exists" in error_effects[0].message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_reducer_create.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement reducer with Create event support**

```python
# src/orca/engine/reducer.py
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from orca.engine.dispatch import backfill_queue, build_issue_context, build_result_format, remove_from_queue, try_dispatch
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
    new_state = copy.deepcopy(state)
    effects: list[Effect] = []

    if isinstance(event, CreateEvent):
        _handle_create(config, new_state, event, effects)
    elif isinstance(event, AdvanceEvent):
        _handle_advance(config, new_state, event, effects)
    elif isinstance(event, WorkerResultEvent):
        _handle_worker_result(config, new_state, event, effects, generate_id)
    elif isinstance(event, WorkerFailedEvent):
        _handle_worker_failed(config, new_state, event, effects)

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
        blocked=False,
        worker_active=False,
        parent=None,
        children=[],
        result_history=[],
    )
    state.issues[event.issue_id] = issue

    initial_def = config.states[config.initial]
    if initial_def.worker is not None:
        dispatch_effects: list[DispatchWorkerEffect] = []
        try_dispatch(config, state, event.issue_id, dispatch_effects)
        effects.extend(dispatch_effects)


def _handle_advance(
    config: StateMachineConfig,
    state: State,
    event: AdvanceEvent,
    effects: list[Effect],
) -> None:
    pass  # Implemented in Task 6


def _handle_worker_result(
    config: StateMachineConfig,
    state: State,
    event: WorkerResultEvent,
    effects: list[Effect],
    generate_id: Callable[[], str],
) -> None:
    pass  # Implemented in Task 7


def _handle_worker_failed(
    config: StateMachineConfig,
    state: State,
    event: WorkerFailedEvent,
    effects: list[Effect],
) -> None:
    pass  # Implemented in Task 8
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_reducer_create.py -v`
Expected: all PASS

- [ ] **Step 5: Run ruff and mypy**

Run: `uv run ruff check src/orca/engine/reducer.py && uv run mypy src/orca/engine/reducer.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/reducer.py tests/engine/test_reducer_create.py
git commit -m "feat: add reducer with Create event handling"
```

---

### Task 6: Reducer — Advance Event

**Files:**
- Modify: `src/orca/engine/reducer.py`
- Create: `tests/engine/test_reducer_advance.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/engine/test_reducer_advance.py
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
)
from orca.engine.reducer import reduce


def _counter() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def test_advance_from_passive_to_active(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    state = State(issues={}, worker_queues={})
    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "T", "text": "D"}), _counter())
    assert state.issues["I-1"].state == "todo"

    state, effects = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="implementing"), _counter())
    assert state.issues["I-1"].state == "implementing"
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
    assert len(dispatch_effects) == 1


def test_advance_from_active_state_errors(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    state = State(issues={}, worker_queues={})
    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "T", "text": "D"}), _counter())
    state, _ = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="implementing"), _counter())
    # Now in implementing (active) — advance should fail
    state, effects = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="done"), _counter())
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
    assert "passive" in error_effects[0].message


def test_advance_blocked_issue_errors(decompose_config_yaml: str) -> None:
    config = parse_config(decompose_config_yaml)
    state = State(issues={}, worker_queues={})
    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "T", "text": "D"}), _counter())
    state.issues["I-1"].blocked = True
    state, effects = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="scoping"), _counter())
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
    assert "blocked" in error_effects[0].message


def test_advance_nonexistent_issue(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    state = State(issues={}, worker_queues={})
    state, effects = reduce(config, state, AdvanceEvent(issue_id="NOPE", target_state="implementing"), _counter())
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1


def test_advance_to_nonexistent_state(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    state = State(issues={}, worker_queues={})
    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "T", "text": "D"}), _counter())
    state, effects = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="nonexistent"), _counter())
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_reducer_advance.py -v`
Expected: FAIL (advance handler is a pass stub)

- [ ] **Step 3: Implement Advance handler in reducer.py**

Replace the `_handle_advance` stub:

```python
def _handle_advance(
    config: StateMachineConfig,
    state: State,
    event: AdvanceEvent,
    effects: list[Effect],
) -> None:
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]
    state_def = config.states.get(issue.state)

    # Must be in a passive state
    if state_def is not None and (state_def.worker is not None or state_def.terminal):
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is not in a passive state")
        )
        return

    if issue.blocked:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is blocked"))
        return

    if event.target_state not in config.states:
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id, message=f"Target state '{event.target_state}' does not exist in config"
            )
        )
        return

    issue.state = event.target_state

    target_def = config.states[event.target_state]
    if target_def.worker is not None:
        dispatch_effects: list[DispatchWorkerEffect] = []
        try_dispatch(config, state, event.issue_id, dispatch_effects)
        effects.extend(dispatch_effects)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_reducer_advance.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/engine/reducer.py tests/engine/test_reducer_advance.py
git commit -m "feat: add Advance event handling to reducer"
```

---

### Task 7: Reducer — WorkerResult Event (Transitions, Decompose, Unblock)

**Files:**
- Modify: `src/orca/engine/reducer.py`
- Create: `tests/engine/test_reducer_worker_result.py`

- [ ] **Step 1: Write failing tests for simple transitions**

```python
# tests/engine/test_reducer_worker_result.py
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
    StateMachineConfig,
    WorkerResultEvent,
)
from orca.engine.reducer import reduce


def _counter() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def _setup_issue_in_state(config_yaml: str, target_state: str) -> tuple[StateMachineConfig, State]:
    """Create an issue and advance it to the target active state."""
    from orca.engine.config import parse_config

    config = parse_config(config_yaml)
    state = State(issues={}, worker_queues={})
    gen = _counter()
    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "T", "text": "D"}), gen)
    if state.issues["I-1"].state != target_state:
        state, _ = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state=target_state), gen)
    return config, state


def test_simple_transition(simple_config_yaml: str) -> None:
    config, state = _setup_issue_in_state(simple_config_yaml, "implementing")
    gen = _counter()
    state, effects = reduce(
        config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done", "summary": "Built it"}), gen
    )
    assert state.issues["I-1"].state == "done"
    assert state.issues["I-1"].worker_active is False
    assert len(state.issues["I-1"].result_history) == 1
    assert state.issues["I-1"].result_history[0].state == "implementing"


def test_transition_to_active_state_dispatches() -> None:
    yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: "t"
    text:
      type: string
      description: "t"
initial: todo
states:
  todo: {}
  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "r"
          values_description:
            done: "d"
        summary:
          type: string
          description: "s"
    on:
      done: testing
  testing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [passed]
          description: "r"
          values_description:
            passed: "p"
    on:
      passed: done
  done:
    terminal: true
"""
    config, state = _setup_issue_in_state(yaml_str, "implementing")
    gen = _counter()
    state, effects = reduce(
        config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done", "summary": "ok"}), gen
    )
    assert state.issues["I-1"].state == "testing"
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
    assert len(dispatch_effects) == 1
    assert dispatch_effects[0].state == "testing"


def test_worker_result_on_blocked_issue_errors(simple_config_yaml: str) -> None:
    config, state = _setup_issue_in_state(simple_config_yaml, "implementing")
    state.issues["I-1"].blocked = True
    gen = _counter()
    state, effects = reduce(
        config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done", "summary": "x"}), gen
    )
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1


def test_worker_result_on_terminal_errors(simple_config_yaml: str) -> None:
    config, state = _setup_issue_in_state(simple_config_yaml, "implementing")
    state.issues["I-1"].state = "done"
    state.issues["I-1"].worker_active = False
    gen = _counter()
    state, effects = reduce(
        config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen
    )
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1


def test_worker_result_when_not_active_errors(simple_config_yaml: str) -> None:
    config, state = _setup_issue_in_state(simple_config_yaml, "implementing")
    state.issues["I-1"].worker_active = False
    gen = _counter()
    state, effects = reduce(
        config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done", "summary": "x"}), gen
    )
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1


def test_decompose_creates_children(decompose_config_yaml: str) -> None:
    config, state = _setup_issue_in_state(decompose_config_yaml, "scoping")
    gen = _counter()
    result = {
        "outcome": "decompose",
        "sub_issues": [
            {"title": "Sub 1", "text": "First"},
            {"title": "Sub 2", "text": "Second"},
        ],
    }
    state, effects = reduce(config, state, WorkerResultEvent(issue_id="I-1", result=result), gen)
    parent = state.issues["I-1"]
    assert parent.blocked is True
    assert parent.state == "scoping"
    assert len(parent.children) == 2

    child_1_id = parent.children[0]
    child_2_id = parent.children[1]
    assert state.issues[child_1_id].fields["title"] == "Sub 1"
    assert state.issues[child_1_id].parent == "I-1"
    assert state.issues[child_1_id].state == "todo"
    assert state.issues[child_2_id].fields["title"] == "Sub 2"


def test_cascading_unblock(decompose_config_yaml: str) -> None:
    config, state = _setup_issue_in_state(decompose_config_yaml, "scoping")
    gen = _counter()

    # Decompose
    result = {
        "outcome": "decompose",
        "sub_issues": [{"title": "Sub 1", "text": "First"}],
    }
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result=result), gen)
    child_id = state.issues["I-1"].children[0]

    # Advance child to scoping, then implementing, then done
    state, _ = reduce(config, state, AdvanceEvent(issue_id=child_id, target_state="scoping"), gen)
    state, _ = reduce(
        config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "ready"}), gen
    )
    assert state.issues[child_id].state == "implementing"

    state, _ = reduce(
        config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "done"}), gen
    )
    assert state.issues[child_id].state == "done"

    # Parent should be unblocked and re-dispatched
    assert state.issues["I-1"].blocked is False
    assert state.issues["I-1"].worker_active is True


def test_slot_backfill_on_worker_result(max_workers_config_yaml: str) -> None:
    config = parse_config(max_workers_config_yaml)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    # Create two issues, advance both to implementing
    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "A"}), gen)
    state, _ = reduce(config, state, CreateEvent(issue_id="I-2", fields={"title": "B"}), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="implementing"), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id="I-2", target_state="implementing"), gen)

    # Both complete implementing, move to apply
    state, _ = reduce(
        config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen
    )
    state, _ = reduce(
        config, state, WorkerResultEvent(issue_id="I-2", result={"outcome": "done"}), gen
    )

    # I-1 should be active in apply, I-2 queued (max_workers: 1)
    assert state.issues["I-1"].state == "apply"
    assert state.issues["I-2"].state == "apply"
    assert state.issues["I-1"].worker_active is True
    assert state.issues["I-2"].worker_active is False

    # I-1 merges — should backfill I-2
    state, effects = reduce(
        config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "merged"}), gen
    )
    assert state.issues["I-1"].state == "done"
    assert state.issues["I-2"].worker_active is True
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
    assert any(e.issue_id == "I-2" for e in dispatch_effects)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_reducer_worker_result.py -v`
Expected: FAIL

- [ ] **Step 3: Implement WorkerResult handler**

Replace the `_handle_worker_result` stub in `src/orca/engine/reducer.py`:

```python
def _handle_worker_result(
    config: StateMachineConfig,
    state: State,
    event: WorkerResultEvent,
    effects: list[Effect],
    generate_id: Callable[[], str],
) -> None:
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]
    state_def = config.states.get(issue.state)

    if state_def is None or state_def.terminal:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is in a terminal state")
        )
        return

    if issue.blocked:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is blocked"))
        return

    if not issue.worker_active:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' has no active worker")
        )
        return

    if state_def.worker is None:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is in a passive state")
        )
        return

    # Step 2: validate outcome before mutating state
    outcome = event.result.get("outcome")
    if outcome is None or outcome not in state_def.on:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"No routing rule for outcome '{outcome}'")
        )
        return

    # Step 3: free slot (after validation passes)
    old_state_name = issue.state
    issue.worker_active = False

    # Step 4: append to result_history
    issue.result_history.append(ResultHistoryEntry(state=issue.state, result=event.result))

    on_rule = state_def.on[outcome]

    if isinstance(on_rule, OnTransition):
        # Step 5: simple transition
        remove_from_queue(state, old_state_name, event.issue_id)
        issue.state = on_rule.target

        target_def = config.states[on_rule.target]
        if target_def.terminal:
            _check_cascading_unblock(config, state, event.issue_id, effects)
        elif target_def.worker is not None:
            dispatch_effects: list[DispatchWorkerEffect] = []
            try_dispatch(config, state, event.issue_id, dispatch_effects)
            effects.extend(dispatch_effects)

    elif isinstance(on_rule, OnDecompose):
        # Step 6: decompose
        sub_issues_data = event.result.get("sub_issues", [])
        child_ids: list[str] = []
        for sub in sub_issues_data:
            child_id = generate_id()
            child = Issue(
                fields=sub,
                state=config.initial,
                blocked=False,
                worker_active=False,
                parent=event.issue_id,
                children=[],
                result_history=[],
            )
            state.issues[child_id] = child
            child_ids.append(child_id)

            initial_def = config.states[config.initial]
            if initial_def.worker is not None:
                child_dispatch: list[DispatchWorkerEffect] = []
                try_dispatch(config, state, child_id, child_dispatch)
                effects.extend(child_dispatch)

        issue.children = child_ids
        issue.blocked = True

    # Backfill queue for old state
    backfill_dispatch: list[DispatchWorkerEffect] = []
    backfill_queue(config, state, old_state_name, backfill_dispatch)
    effects.extend(backfill_dispatch)


def _check_cascading_unblock(
    config: StateMachineConfig,
    state: State,
    issue_id: str,
    effects: list[Effect],
) -> None:
    issue = state.issues[issue_id]
    if issue.parent is None:
        return

    parent = state.issues[issue.parent]
    if not parent.blocked:
        return

    # Check if all children of parent are terminal
    all_terminal = all(
        config.states[state.issues[child_id].state].terminal for child_id in parent.children
    )
    if not all_terminal:
        return

    parent.blocked = False
    dispatch_effects: list[DispatchWorkerEffect] = []
    try_dispatch(config, state, issue.parent, dispatch_effects)
    effects.extend(dispatch_effects)

    # Recursive: if parent just got unblocked and its state is terminal, check its parent
    parent_state_def = config.states[parent.state]
    if parent_state_def.terminal:
        _check_cascading_unblock(config, state, issue.parent, effects)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_reducer_worker_result.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/reducer.py tests/engine/test_reducer_worker_result.py
git commit -m "feat: add WorkerResult handling with transitions, decompose, and cascading unblock"
```

---

### Task 8: Reducer — WorkerFailed Event

**Files:**
- Modify: `src/orca/engine/reducer.py`
- Create: `tests/engine/test_reducer_worker_failed.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/engine/test_reducer_worker_failed.py
from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
    WorkerFailedEvent,
    WorkerResultEvent,
)
from orca.engine.reducer import reduce


def _counter() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def test_worker_failed_retries(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    gen = _counter()
    state = State(issues={}, worker_queues={})
    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "T", "text": "D"}), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="implementing"), gen)
    assert state.issues["I-1"].worker_active is True

    state, effects = reduce(config, state, WorkerFailedEvent(issue_id="I-1", error="timeout"), gen)
    # worker_active stays True (slot retained)
    assert state.issues["I-1"].worker_active is True
    assert state.issues["I-1"].state == "implementing"
    dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
    assert len(dispatch_effects) == 1
    assert dispatch_effects[0].issue_id == "I-1"


def test_worker_failed_does_not_free_slot(max_workers_config_yaml: str) -> None:
    config = parse_config(max_workers_config_yaml)
    gen = _counter()
    state = State(issues={}, worker_queues={})

    state, _ = reduce(config, state, CreateEvent(issue_id="I-1", fields={"title": "A"}), gen)
    state, _ = reduce(config, state, CreateEvent(issue_id="I-2", fields={"title": "B"}), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id="I-1", target_state="implementing"), gen)
    state, _ = reduce(config, state, AdvanceEvent(issue_id="I-2", target_state="implementing"), gen)

    # Both to apply
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-1", result={"outcome": "done"}), gen)
    state, _ = reduce(config, state, WorkerResultEvent(issue_id="I-2", result={"outcome": "done"}), gen)

    # I-1 active in apply, I-2 queued
    assert state.issues["I-1"].worker_active is True
    assert state.issues["I-2"].worker_active is False

    # I-1 fails — slot should NOT free, I-2 should stay queued
    state, effects = reduce(config, state, WorkerFailedEvent(issue_id="I-1", error="crash"), gen)
    assert state.issues["I-1"].worker_active is True
    assert state.issues["I-2"].worker_active is False


def test_worker_failed_nonexistent_issue(simple_config_yaml: str) -> None:
    config = parse_config(simple_config_yaml)
    state = State(issues={}, worker_queues={})
    state, effects = reduce(config, state, WorkerFailedEvent(issue_id="NOPE", error="x"), _counter())
    error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
    assert len(error_effects) == 1
```

We need to add the missing import at the top:

```python
from orca.engine.types import WorkerResultEvent
```

(Add this to the imports in the test file since `test_worker_failed_does_not_free_slot` uses it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_reducer_worker_failed.py -v`
Expected: FAIL

- [ ] **Step 3: Implement WorkerFailed handler**

Replace the `_handle_worker_failed` stub in `src/orca/engine/reducer.py`:

```python
def _handle_worker_failed(
    config: StateMachineConfig,
    state: State,
    event: WorkerFailedEvent,
    effects: list[Effect],
) -> None:
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]

    if not issue.worker_active:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' has no active worker")
        )
        return

    state_def = config.states[issue.state]
    if state_def.worker is None:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is in a state without a worker")
        )
        return

    # Unconditional retry — slot retained, bypass dispatch protocol
    effects.append(
        DispatchWorkerEffect(
            issue_id=event.issue_id,
            state=issue.state,
            result_format=build_result_format(config, issue.state),
            issue=build_issue_context(state, event.issue_id),
        )
    )
```

Note: This bypasses the dispatch protocol intentionally — per spec, the failed issue retains its slot (`worker_active` stays `True`) and the retry is unconditional. `build_issue_context` and `build_result_format` are public functions from `dispatch.py` (imported at the top of `reducer.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_reducer_worker_failed.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/reducer.py tests/engine/test_reducer_worker_failed.py
git commit -m "feat: add WorkerFailed event handling with slot retention and retry"
```

---

### Task 9: Public API and Module Exports

**Files:**
- Modify: `src/orca/engine/__init__.py`

- [ ] **Step 1: Write failing test for public API**

```python
# Add to tests/engine/test_types.py at the end:

def test_public_api_imports() -> None:
    from orca.engine import (
        reduce,
        parse_config,
        ConfigValidationError,
        State,
        Issue,
        CreateEvent,
        AdvanceEvent,
        WorkerResultEvent,
        WorkerFailedEvent,
        DispatchWorkerEffect,
        ErrorEffect,
        StateMachineConfig,
    )
    assert callable(reduce)
    assert callable(parse_config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_types.py::test_public_api_imports -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement exports**

```python
# src/orca/engine/__init__.py
"""Orca state machine engine."""

from orca.engine.config import ConfigValidationError, parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    Issue,
    State,
    StateMachineConfig,
    WorkerFailedEvent,
    WorkerResultEvent,
)

__all__ = [
    "ConfigValidationError",
    "parse_config",
    "reduce",
    "AdvanceEvent",
    "CreateEvent",
    "DispatchWorkerEffect",
    "ErrorEffect",
    "Issue",
    "State",
    "StateMachineConfig",
    "WorkerFailedEvent",
    "WorkerResultEvent",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_types.py::test_public_api_imports -v`
Expected: PASS

- [ ] **Step 5: Run full test suite + ruff + mypy**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy src/`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/__init__.py tests/engine/test_types.py
git commit -m "feat: add public API exports for engine module"
```

---

### Task 10: Final Verification — Full Test Suite, Lint, Type Check

**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 2: Run ruff**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS

- [ ] **Step 3: Run mypy**

Run: `uv run mypy src/`
Expected: PASS

- [ ] **Step 4: Verify CI config includes tests**

Check `.github/workflows/ci.yml` — if tests aren't in CI yet, add a `test` job:

```yaml
  test:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - name: Install dependencies
        run: uv sync
      - name: Run tests
        run: uv run pytest -v
```

- [ ] **Step 5: Commit CI update if needed**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add test job to CI pipeline"
```
