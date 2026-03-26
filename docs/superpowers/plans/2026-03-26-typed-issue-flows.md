# Typed Issue Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add issue types to the state machine so decomposed children can follow different flows than their parent.

**Architecture:** Replace the single flat `StateMachineConfig` (one `initial`, one `states` dict, one `issue_fields`) with a `types` map where each type defines its own fields, initial state, and state machine. The `OnDecompose` rule gains a `child_type` default, and workers can override the type per-child. Queue keys change from `state_name` to `(type, state)`.

**Tech Stack:** Python 3.12, dataclasses, PyYAML, pytest, ruff, mypy

---

## File Map

- **Modify:** `src/orca/engine/types.py` — Add `TypeDef`, `type` field on `Issue`, `issue_type` on `DispatchWorkerEffect`, change `StateMachineConfig` shape, update `State.worker_queues` key type
- **Modify:** `src/orca/engine/config.py` — Parse `types`/`root_type` from YAML, validate per-type state machines, validate `child_type` references
- **Modify:** `src/orca/engine/dispatch.py` — Type-aware state lookups, `(type, state)` queue keys
- **Modify:** `src/orca/engine/reducer.py` — Type-aware state lookups, type-aware decomposition, type-aware field merging
- **Modify:** `src/orca/engine/formatting.py` — Show `[type:state]` in ASCII tree
- **Modify:** `src/orca/orchestrator/orchestrator.py` — Use `issue_type` from effect for state lookups
- **Modify:** `src/orca/orchestrator/runner.py` — Use `config.root_type` for root issue creation, type-aware `build_result_format`/`_recover_effects`
- **Modify:** `tests/engine/conftest.py` — Update fixture configs to typed format
- **Modify:** `tests/engine/test_config.py` — Update all config tests for typed format
- **Modify:** `tests/engine/test_scenario_decompose.py` — Update decompose tests for typed children
- **Modify:** Multiple other test files that use `config.states` or `config.initial` directly

---

### Task 1: Add `TypeDef` and reshape `StateMachineConfig` in types.py

**Files:**
- Modify: `src/orca/engine/types.py`
- Test: `tests/engine/test_types.py`

- [ ] **Step 1: Write failing test for TypeDef and new StateMachineConfig shape**

In `tests/engine/test_types.py`, add:

```python
from orca.engine.types import TypeDef, StateMachineConfig, FieldDef, StateDef


class TestTypeDef:
    def test_type_def_holds_fields_initial_states(self) -> None:
        td = TypeDef(
            fields={"title": FieldDef(type="string", description="t")},
            initial="todo",
            states={"todo": StateDef(terminal=True)},
        )
        assert td.initial == "todo"
        assert "title" in td.fields
        assert "todo" in td.states


class TestStateMachineConfigWithTypes:
    def test_config_has_root_type_and_types(self) -> None:
        td = TypeDef(
            fields={},
            initial="done",
            states={"done": StateDef(terminal=True)},
        )
        cfg = StateMachineConfig(
            root_type="epic",
            types={"epic": td},
            max_hops=None,
            max_worker_retries=5,
        )
        assert cfg.root_type == "epic"
        assert "epic" in cfg.types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_types.py::TestTypeDef -v`
Expected: FAIL — `TypeDef` does not exist, `StateMachineConfig` has wrong fields

- [ ] **Step 3: Add TypeDef, reshape StateMachineConfig, add child_type to OnDecompose**

In `src/orca/engine/types.py`:

Add `TypeDef` after `StateDef`:

```python
@dataclass(frozen=True)
class TypeDef:
    fields: dict[str, FieldDef]
    initial: str
    states: dict[str, StateDef]
```

Replace `StateMachineConfig` with:

```python
@dataclass(frozen=True)
class StateMachineConfig:
    root_type: str
    types: dict[str, TypeDef]
    max_hops: int | None = None
    max_worker_retries: int = 5
```

Add `child_type` to `OnDecompose`:

```python
@dataclass(frozen=True)
class OnDecompose:
    child_type: str | None = None
    then: str | None = None
```

Add `type` field to `Issue` (first field, before `fields`):

```python
@dataclass
class Issue:
    type: str
    fields: dict[str, Any]
    state: str
    worker_active: bool
    decomposed_from: str | None
    depends_on: list[str]
    event_log: list[EventLogEntry]
    visit_counts: dict[str, int] = field(default_factory=dict)
    hop_count: int = 0
    failure_count: int = 0
```

Update `Issue.to_dict` to include `"type": self.type`.

Update `Issue.from_dict` to read `type=data["type"]`.

Add `issue_type` field to `DispatchWorkerEffect`:

```python
@dataclass(frozen=True)
class DispatchWorkerEffect:
    issue_id: str
    issue_type: str
    state: str
    result_format: dict[str, Any]
    issue: dict[str, Any]
```

Change `State.worker_queues` key type from `str` to a serializable format. Since dict keys must be strings in JSON, use `str` keys with format `"{type}:{state}"`:

```python
@dataclass
class State:
    issues: dict[str, Issue]
    worker_queues: dict[str, list[str]]  # key = "{type}:{state}"
```

(The key format changes but the type annotation stays `dict[str, list[str]]` for JSON compatibility. The semantic change is in how keys are constructed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_types.py::TestTypeDef tests/engine/test_types.py::TestStateMachineConfigWithTypes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/engine/types.py tests/engine/test_types.py
git commit -m "feat: add TypeDef, reshape StateMachineConfig for typed issue flows"
```

---

### Task 2: Add helper methods to StateMachineConfig for type-aware lookups

**Files:**
- Modify: `src/orca/engine/types.py`
- Test: `tests/engine/test_types.py`

To avoid scattering `config.types[issue.type].states[issue.state]` everywhere, add helper methods on `StateMachineConfig`. Since it's frozen, these are read-only methods.

- [ ] **Step 1: Write failing test**

In `tests/engine/test_types.py`, add:

```python
class TestConfigHelpers:
    def _make_config(self) -> StateMachineConfig:
        from orca.engine.types import WorkerDef, EnumFieldDef, OnTransition

        worker = WorkerDef(
            kind="claude-code",
            prompt="p.md",
            result_format={"outcome": EnumFieldDef(values=["done"], description="d")},
        )
        epic = TypeDef(
            fields={"title": FieldDef(type="string", description="t")},
            initial="todo",
            states={
                "todo": StateDef(worker=worker, on={"done": OnTransition(target="done")}),
                "done": StateDef(terminal=True),
            },
        )
        return StateMachineConfig(root_type="epic", types={"epic": epic})

    def test_get_type_def(self) -> None:
        cfg = self._make_config()
        td = cfg.get_type("epic")
        assert td.initial == "todo"

    def test_get_state_def(self) -> None:
        cfg = self._make_config()
        sd = cfg.get_state("epic", "todo")
        assert sd.worker is not None

    def test_get_state_def_unknown_type_raises(self) -> None:
        cfg = self._make_config()
        with pytest.raises(KeyError):
            cfg.get_state("unknown", "todo")

    def test_root_type_def(self) -> None:
        cfg = self._make_config()
        td = cfg.root_type_def
        assert td.initial == "todo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_types.py::TestConfigHelpers -v`
Expected: FAIL — methods don't exist

- [ ] **Step 3: Add helper methods to StateMachineConfig**

In `src/orca/engine/types.py`, add methods to `StateMachineConfig`:

```python
@dataclass(frozen=True)
class StateMachineConfig:
    root_type: str
    types: dict[str, TypeDef]
    max_hops: int | None = None
    max_worker_retries: int = 5

    def get_type(self, type_name: str) -> TypeDef:
        return self.types[type_name]

    def get_state(self, type_name: str, state_name: str) -> StateDef:
        return self.types[type_name].states[state_name]

    @property
    def root_type_def(self) -> TypeDef:
        return self.types[self.root_type]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_types.py::TestConfigHelpers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/engine/types.py tests/engine/test_types.py
git commit -m "feat: add helper methods to StateMachineConfig for type-aware lookups"
```

---

### Task 3: Update config parser for typed format

**Files:**
- Modify: `src/orca/engine/config.py`
- Test: `tests/engine/test_config.py`

- [ ] **Step 1: Write failing test for multi-type config parsing**

In `tests/engine/test_config.py`, add a new test class:

```python
class TestParseTypedConfig:
    TYPED_YAML = """\
root_type: epic
max_hops: 15

types:
  epic:
    fields:
      title: {type: string, description: "Title"}
      scope: {type: string, description: "Scope"}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scope.md
          result_format:
            outcome:
              type: enum
              values: [ready, decompose]
              description: d
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
              description: s
        on:
          ready: done
          decompose:
            action: decompose
            child_type: task
            then: done
      done:
        terminal: true

  task:
    fields:
      title: {type: string, description: "Title"}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/impl.md
          result_format:
            outcome:
              type: enum
              values: [done]
              description: d
        on:
          done: done
      done:
        terminal: true
"""

    def test_root_type(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert cfg.root_type == "epic"

    def test_types_parsed(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert set(cfg.types.keys()) == {"epic", "task"}

    def test_epic_fields(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert "title" in cfg.types["epic"].fields
        assert "scope" in cfg.types["epic"].fields

    def test_task_initial(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert cfg.types["task"].initial == "implementing"

    def test_decompose_child_type(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        rule = cfg.types["epic"].states["scoping"].on["decompose"]
        assert isinstance(rule, OnDecompose)
        assert rule.child_type == "task"

    def test_max_hops(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert cfg.max_hops == 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_config.py::TestParseTypedConfig -v`
Expected: FAIL — parser doesn't understand `types` key

- [ ] **Step 3: Rewrite config parser for typed format**

In `src/orca/engine/config.py`:

Update `_parse_on_rule` to pass through `child_type`:

```python
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
```

Add `TypeDef` to imports and add a `_parse_type` function:

```python
from orca.engine.types import TypeDef

def _parse_type(name: str, raw: dict[str, Any]) -> TypeDef:
    fields_data = raw.get("fields")
    fields = _parse_issue_fields(fields_data)
    initial = raw.get("initial", "")
    states_data: dict[str, Any] = raw.get("states", {})
    states: dict[str, StateDef] = {}
    for state_name, state_data in states_data.items():
        states[state_name] = _parse_state(state_name, state_data)
    return TypeDef(fields=fields, initial=initial, states=states)
```

Rewrite `parse_config` to detect typed vs legacy format:

```python
def parse_config(yaml_str: str) -> StateMachineConfig:
    raw: Any = yaml.safe_load(yaml_str)
    if not isinstance(raw, dict):
        msg = "Config must be a YAML mapping"
        raise ConfigValidationError(msg)

    if "types" in raw:
        return _parse_typed_config(raw)
    return _parse_legacy_config(raw)
```

Add `_parse_typed_config`:

```python
def _parse_typed_config(raw: dict[str, Any]) -> StateMachineConfig:
    root_type = raw.get("root_type", "")
    max_hops = raw.get("max_hops")
    max_worker_retries = raw.get("max_worker_retries", 5)

    types_data: dict[str, Any] = raw.get("types", {})
    types: dict[str, TypeDef] = {}
    for name, type_data in types_data.items():
        types[name] = _parse_type(name, type_data)

    config = StateMachineConfig(
        root_type=root_type,
        types=types,
        max_hops=max_hops,
        max_worker_retries=max_worker_retries,
    )
    _validate(config)
    return config
```

Move the old `parse_config` body into `_parse_legacy_config` which wraps the single state machine into a `TypeDef` named `"default"`:

```python
def _parse_legacy_config(raw: dict[str, Any]) -> StateMachineConfig:
    issue_data = raw.get("issue", {})
    fields_data = issue_data.get("fields") if isinstance(issue_data, dict) else None
    issue_fields = _parse_issue_fields(fields_data)

    states_data: dict[str, Any] = raw.get("states", {})
    states: dict[str, StateDef] = {}
    for name, state_data in states_data.items():
        states[name] = _parse_state(name, state_data)

    initial: str = raw.get("initial", "")
    max_hops = raw.get("max_hops")
    max_worker_retries = raw.get("max_worker_retries", 5)

    type_def = TypeDef(fields=issue_fields, initial=initial, states=states)

    config = StateMachineConfig(
        root_type="default",
        types={"default": type_def},
        max_hops=max_hops,
        max_worker_retries=max_worker_retries,
    )
    _validate(config)
    return config
```

- [ ] **Step 4: Update `_validate` for typed config**

Rewrite `_validate` to iterate over all types:

```python
def _validate(config: StateMachineConfig) -> None:
    # root_type must exist
    if config.root_type not in config.types:
        msg = f"root_type '{config.root_type}' does not reference an existing type"
        raise ConfigValidationError(msg)

    if config.max_hops is not None and (not isinstance(config.max_hops, int) or config.max_hops < 1):
        msg = f"max_hops must be a positive integer, got {config.max_hops}"
        raise ConfigValidationError(msg)

    for type_name, type_def in config.types.items():
        _validate_type(config, type_name, type_def)


def _validate_type(config: StateMachineConfig, type_name: str, type_def: TypeDef) -> None:
    state_names = set(type_def.states.keys())

    # initial references an existing state within this type
    if type_def.initial not in state_names:
        msg = f"Type '{type_name}': initial state '{type_def.initial}' does not exist"
        raise ConfigValidationError(msg)

    # At least one terminal state
    terminal_states = {name for name, s in type_def.states.items() if s.terminal}
    if not terminal_states:
        msg = f"Type '{type_name}': at least one terminal state is required"
        raise ConfigValidationError(msg)

    reachable: set[str] = {type_def.initial}

    for name, state in type_def.states.items():
        # Worker validation
        if state.worker is not None:
            if state.worker.kind not in _ALLOWED_WORKER_KINDS:
                allowed_kinds = sorted(_ALLOWED_WORKER_KINDS)
                msg = f"Type '{type_name}', state '{name}': kind must be one of {allowed_kinds}, got '{state.worker.kind}'"
                raise ConfigValidationError(msg)
            if not state.worker.prompt:
                msg = f"Type '{type_name}', state '{name}': prompt must be non-empty"
                raise ConfigValidationError(msg)
            if state.worker.timeout is not None and (
                not isinstance(state.worker.timeout, int) or state.worker.timeout < 1
            ):
                msg = f"Type '{type_name}', state '{name}': timeout must be positive integer, got {state.worker.timeout}"
                raise ConfigValidationError(msg)

        if state.max_workers is not None and (not isinstance(state.max_workers, int) or state.max_workers < 1):
            msg = f"Type '{type_name}', state '{name}': max_workers must be positive integer, got {state.max_workers}"
            raise ConfigValidationError(msg)

        if state.max_visits is not None and (not isinstance(state.max_visits, int) or state.max_visits < 1):
            msg = f"Type '{type_name}', state '{name}': max_visits must be positive integer, got {state.max_visits}"
            raise ConfigValidationError(msg)

        if state.terminal:
            if state.worker is not None or state.on:
                msg = f"Type '{type_name}': terminal state '{name}' must not have worker or on rules"
                raise ConfigValidationError(msg)
            continue

        if state.worker is not None and state.on:
            outcome = state.worker.result_format.get("outcome")
            if not isinstance(outcome, EnumFieldDef):
                msg = f"Type '{type_name}', state '{name}': must have 'outcome' enum in result_format"
                raise ConfigValidationError(msg)
            for key in state.on:
                if key not in outcome.values:
                    msg = f"Type '{type_name}', state '{name}': on key '{key}' not in outcome values ({outcome.values})"
                    raise ConfigValidationError(msg)

        # on targets must be within the same type
        for key, rule in state.on.items():
            if isinstance(rule, OnTransition):
                if rule.target not in state_names:
                    msg = f"Type '{type_name}', state '{name}': on.{key} target '{rule.target}' does not exist"
                    raise ConfigValidationError(msg)
                reachable.add(rule.target)
            elif isinstance(rule, OnDecompose):
                if rule.then is not None and rule.then not in state_names:
                    msg = f"Type '{type_name}', state '{name}': decompose then '{rule.then}' does not exist"
                    raise ConfigValidationError(msg)
                if rule.then is not None:
                    reachable.add(rule.then)
                # child_type must reference an existing type
                if rule.child_type is not None and rule.child_type not in config.types:
                    msg = f"Type '{type_name}', state '{name}': child_type '{rule.child_type}' does not exist"
                    raise ConfigValidationError(msg)

        # decompose requires sub_issues field
        for _key, rule in state.on.items():
            if isinstance(rule, OnDecompose):
                if state.worker is None:
                    msg = f"Type '{type_name}', state '{name}': decompose action but no worker"
                    raise ConfigValidationError(msg)
                sub = state.worker.result_format.get("sub_issues")
                if not isinstance(sub, ListFieldDef) or sub.items != "$issue":
                    msg = f"Type '{type_name}', state '{name}': decompose requires sub_issues with items: $issue"
                    raise ConfigValidationError(msg)

    # Reachability check
    for name, state in type_def.states.items():
        if name in reachable:
            continue
        is_passive = state.worker is None and not state.on and not state.terminal
        if is_passive:
            continue
        msg = f"Type '{type_name}', state '{name}': not reachable from any on rule"
        raise ConfigValidationError(msg)
```

- [ ] **Step 5: Run tests to verify typed parsing works**

Run: `uv run pytest tests/engine/test_config.py::TestParseTypedConfig -v`
Expected: PASS

- [ ] **Step 6: Update existing config tests for legacy compatibility**

The existing tests use legacy format (no `types` key). With `_parse_legacy_config`, they should still parse but the config shape changes. Update test assertions:

In `tests/engine/test_config.py`, update `TestParseSimpleConfig`:

```python
class TestParseSimpleConfig:
    def test_states_exist(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert set(cfg.types["default"].states.keys()) == {"todo", "implementing", "done"}

    def test_initial_state(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.types["default"].initial == "todo"

    def test_terminal_state(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.types["default"].states["done"].terminal is True

    def test_active_state_worker(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        state = cfg.types["default"].states["todo"]
        assert state.worker is not None
        assert "outcome" in state.worker.result_format
        outcome = state.worker.result_format["outcome"]
        assert isinstance(outcome, EnumFieldDef)
        assert outcome.values == ["start"]

    def test_on_rules(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.types["default"].states["todo"].on == {"start": OnTransition(target="implementing")}
        assert cfg.types["default"].states["implementing"].on == {
            "complete": OnTransition(target="done"),
            "reject": OnTransition(target="todo"),
        }

    def test_string_result_format_field(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        rf = cfg.types["default"].states["implementing"].worker
        assert rf is not None
        reason = rf.result_format["reason"]
        assert isinstance(reason, StringFieldDef)

    def test_required_when_normalization(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        rf = cfg.types["default"].states["implementing"].worker
        assert rf is not None
        reason = rf.result_format["reason"]
        assert isinstance(reason, StringFieldDef)
        assert reason.required_when == ["reject"]
```

Similarly update `TestParseDecomposeConfig`, `TestParseMaxWorkersConfig`, `TestParseIssueFields`, and all `TestValidationErrors` tests to use `cfg.types["default"]` or `cfg.root_type_def` where they previously used `cfg.states` / `cfg.initial` / `cfg.issue_fields`.

Update all validation error tests — they should still raise the same errors but error messages may now include "Type 'default'" prefix.

- [ ] **Step 7: Add validation tests for typed config errors**

```python
class TestTypedConfigValidation:
    def test_root_type_must_exist(self) -> None:
        yaml_str = """\
root_type: ghost
types:
  epic:
    fields: {}
    initial: done
    states:
      done: {terminal: true}
"""
        with pytest.raises(ConfigValidationError, match="root_type.*ghost"):
            parse_config(yaml_str)

    def test_child_type_must_exist(self) -> None:
        yaml_str = """\
root_type: epic
types:
  epic:
    fields: {}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: p.md
          result_format:
            outcome: {type: enum, values: [decompose], description: d}
            sub_issues: {type: list, items: "$issue", required_when: [decompose], description: s}
        on:
          decompose:
            action: decompose
            child_type: ghost
      done: {terminal: true}
"""
        with pytest.raises(ConfigValidationError, match="child_type.*ghost"):
            parse_config(yaml_str)

    def test_cross_type_transition_rejected(self) -> None:
        """on targets must reference states within the same type."""
        yaml_str = """\
root_type: epic
types:
  epic:
    fields: {}
    initial: todo
    states:
      todo:
        worker:
          kind: claude-code
          prompt: p.md
          result_format:
            outcome: {type: enum, values: [go], description: d}
        on:
          go: implementing
      done: {terminal: true}
  task:
    fields: {}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: p.md
          result_format:
            outcome: {type: enum, values: [done], description: d}
        on:
          done: done
      done: {terminal: true}
"""
        with pytest.raises(ConfigValidationError, match="implementing.*does not exist"):
            parse_config(yaml_str)
```

- [ ] **Step 8: Run all config tests**

Run: `uv run pytest tests/engine/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add src/orca/engine/config.py tests/engine/test_config.py
git commit -m "feat: config parser supports typed format with legacy backward compat"
```

---

### Task 4: Update dispatch.py for type-aware lookups

**Files:**
- Modify: `src/orca/engine/dispatch.py`
- Test: `tests/engine/test_dispatch.py`

Every function in dispatch.py that does `config.states[...]` must become type-aware. The issue's `type` field determines which type's states to look up.

- [ ] **Step 1: Write failing test for type-aware dispatch**

In `tests/engine/test_dispatch.py`, add:

```python
from orca.engine.types import (
    DispatchWorkerEffect,
    EnumFieldDef,
    FieldDef,
    Issue,
    OnTransition,
    State,
    StateDef,
    StateMachineConfig,
    TypeDef,
    WorkerDef,
)
from orca.engine.dispatch import is_blocked, try_dispatch, build_result_format, build_issue_context


def _typed_config() -> StateMachineConfig:
    """Config with two types: epic (scoping->done) and task (implementing->done)."""
    worker_scope = WorkerDef(
        kind="claude-code",
        prompt="p.md",
        result_format={"outcome": EnumFieldDef(values=["done"], description="d")},
    )
    worker_impl = WorkerDef(
        kind="claude-code",
        prompt="q.md",
        result_format={"outcome": EnumFieldDef(values=["done"], description="d")},
    )
    epic = TypeDef(
        fields={"title": FieldDef(type="string", description="t")},
        initial="scoping",
        states={
            "scoping": StateDef(worker=worker_scope, on={"done": OnTransition(target="done")}),
            "done": StateDef(terminal=True),
        },
    )
    task = TypeDef(
        fields={"title": FieldDef(type="string", description="t")},
        initial="implementing",
        states={
            "implementing": StateDef(worker=worker_impl, on={"done": OnTransition(target="done")}),
            "done": StateDef(terminal=True),
        },
    )
    return StateMachineConfig(root_type="epic", types={"epic": epic, "task": task})


class TestTypedDispatch:
    def test_dispatch_uses_issue_type(self) -> None:
        config = _typed_config()
        issue = Issue(
            type="task",
            fields={"title": "t"},
            state="implementing",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
        )
        state = State(issues={"T1": issue}, worker_queues={})
        effects: list[DispatchWorkerEffect] = []
        try_dispatch(config, state, "T1", effects)
        assert len(effects) == 1
        assert effects[0].issue_type == "task"
        assert effects[0].state == "implementing"

    def test_build_result_format_type_aware(self) -> None:
        config = _typed_config()
        rf = build_result_format(config, "task", "implementing")
        assert "outcome" in rf
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_dispatch.py::TestTypedDispatch -v`
Expected: FAIL — functions don't accept type parameter / Issue missing type

- [ ] **Step 3: Update all dispatch.py functions for type-aware lookups**

In `src/orca/engine/dispatch.py`:

Update `is_blocked` — child state lookup needs the child's type:

```python
def is_blocked(state: State, config: StateMachineConfig, issue_id: str) -> bool:
    issue = state.issues[issue_id]
    children = get_children(state, issue_id)
    if children:
        for child_id in children:
            child = state.issues[child_id]
            child_state_def = config.get_state(child.type, child.state)
            if not child_state_def.terminal:
                return True
    for dep_id in issue.depends_on:
        dep = state.issues[dep_id]
        dep_state_def = config.get_state(dep.type, dep.state)
        if not dep_state_def.terminal:
            return True
    return False
```

Update `build_result_format` to take `type_name` parameter:

```python
def build_result_format(config: StateMachineConfig, type_name: str, state_name: str) -> dict[str, Any]:
    state_def = config.get_state(type_name, state_name)
    if state_def.worker is None:
        return {}
    # ... rest unchanged
```

Update `try_dispatch` — look up state via issue type, use `(type, state)` queue key, include `issue_type` in effect:

```python
def try_dispatch(config: StateMachineConfig, state: State, issue_id: str, effects: list[Effect]) -> None:
    issue = state.issues[issue_id]
    state_name = issue.state
    state_def = config.get_state(issue.type, state_name)

    if is_blocked(state, config, issue_id):
        return
    if state_def.worker is None:
        return

    if state_def.max_workers is not None:
        active_count = sum(
            1 for iss in state.issues.values()
            if iss.type == issue.type and iss.state == state_name and iss.worker_active
        )
        if active_count >= state_def.max_workers:
            queue_key = f"{issue.type}:{state_name}"
            queue = state.worker_queues.setdefault(queue_key, [])
            queue.append(issue_id)
            return

    issue.worker_active = True
    effects.append(
        DispatchWorkerEffect(
            issue_id=issue_id,
            issue_type=issue.type,
            state=state_name,
            result_format=build_result_format(config, issue.type, state_name),
            issue=build_issue_context(state, issue_id),
        )
    )
```

Update `backfill_queue` — the `state_name` parameter becomes a queue key (already `"{type}:{state}"`):

```python
def backfill_queue(config: StateMachineConfig, state: State, queue_key: str, effects: list[Effect]) -> None:
    queue = state.worker_queues.get(queue_key)
    if not queue:
        return
    for i, issue_id in enumerate(queue):
        if not is_blocked(state, config, issue_id):
            queue.pop(i)
            try_dispatch(config, state, issue_id, effects)
            return
```

Update `remove_from_queue` — caller passes queue key:

```python
def remove_from_queue(state: State, queue_key: str, issue_id: str) -> None:
    queue = state.worker_queues.get(queue_key)
    if queue is None:
        return
    with contextlib.suppress(ValueError):
        queue.remove(issue_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_dispatch.py::TestTypedDispatch -v`
Expected: PASS

- [ ] **Step 5: Update existing dispatch tests**

Update existing tests in `tests/engine/test_dispatch.py` to construct configs with the new `StateMachineConfig` shape (using `TypeDef`) and pass `type="default"` on Issue objects. All Issues created in tests need the `type` field.

- [ ] **Step 6: Run all dispatch tests**

Run: `uv run pytest tests/engine/test_dispatch.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/engine/dispatch.py tests/engine/test_dispatch.py
git commit -m "feat: type-aware dispatch with (type, state) queue keys"
```

---

### Task 5: Update reducer.py for type-aware state machine

**Files:**
- Modify: `src/orca/engine/reducer.py`

This is the largest change. Every `config.states[...]` becomes `config.get_state(issue.type, ...)`, and decomposition creates typed children.

- [ ] **Step 1: Update `_handle_create`**

Use `config.root_type` and `config.root_type_def`:

```python
def _handle_create(config, state, event, effects, ts):
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
    append_log(issue, event.timestamp, "created", {"state": root_td.initial})

    state_def = config.get_state(config.root_type, root_td.initial)
    if state_def.worker is not None:
        prev_len = len(effects)
        try_dispatch(config, state, event.issue_id, effects)
        if len(effects) > prev_len:
            append_log(issue, ts, "worker_dispatched", {"state": issue.state})
```

- [ ] **Step 2: Update `_handle_advance`**

All `config.states[...]` → `config.get_state(issue.type, ...)`:

```python
def _handle_advance(config, state, event, effects, ts):
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]
    current_state_def = config.get_state(issue.type, issue.state)

    if current_state_def.worker is not None or current_state_def.terminal:
        effects.append(ErrorEffect(
            issue_id=event.issue_id,
            message=f"Issue '{event.issue_id}' is not in a passive state (current: '{issue.state}')",
        ))
        return

    if is_blocked(state, config, event.issue_id):
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is blocked"))
        return

    # Target state must exist within the issue's type
    type_def = config.get_type(issue.type)
    if event.target_state not in type_def.states:
        effects.append(ErrorEffect(
            issue_id=event.issue_id,
            message=f"State '{event.target_state}' does not exist in type '{issue.type}'",
        ))
        return

    # ... rest follows same pattern, replacing config.states[x] with config.get_state(issue.type, x)
```

- [ ] **Step 3: Update `_handle_worker_result`**

Replace `config.states[issue.state]` with `config.get_state(issue.type, issue.state)`.

Replace field merging: instead of `key in config.issue_fields`, use `key in config.get_type(issue.type).fields`:

```python
    # Merge result fields back into issue fields
    type_fields = config.get_type(issue.type).fields
    for key, value in event.result.items():
        if key != "outcome" and key in type_fields:
            issue.fields[key] = value
```

Update queue key for backfill:

```python
    if state_def.max_workers is not None:
        queue_key = f"{issue.type}:{old_state_name}"
        backfill_queue(config, state, queue_key, dispatch_effects)
```

- [ ] **Step 4: Update `_apply_transition`**

Replace `config.states[target_state]` with `config.get_state(issue.type, target_state)`.

Update `remove_from_queue` call to use queue key:

```python
    queue_key = f"{issue.type}:{old_state_name}"
    remove_from_queue(state, queue_key, issue_id)
```

- [ ] **Step 5: Update `_apply_decompose` for typed children**

This is the key change. Children get their type from the decompose rule's `child_type` (default) or the worker's per-child `type` override:

```python
def _apply_decompose(config, state, event, _parent_issue, generate_id, effects, ts):
    sub_issues: list[dict[str, object]] = event.result.get("sub_issues", [])

    append_log(_parent_issue, ts, "decomposition_blocked", {})
    _parent_issue.hop_count += 1

    # Find the decompose rule to get default child_type
    parent_state_def = config.get_state(_parent_issue.type, _parent_issue.state)
    outcome = event.result.get("outcome")
    rule = parent_state_def.on[outcome]
    assert isinstance(rule, OnDecompose)
    default_child_type = rule.child_type

    key_to_id: dict[str, str] = {}
    for sub in sub_issues:
        key = str(sub.get("key", ""))
        real_id = generate_id()
        key_to_id[key] = real_id

    for sub in sub_issues:
        key = str(sub.get("key", ""))
        real_id = key_to_id[key]
        fields: dict[str, object] = sub.get("fields", {})

        # Resolve child type
        child_type_name = str(sub.get("type", "")) if "type" in sub else None
        if child_type_name is None or child_type_name == "":
            child_type_name = default_child_type
        if child_type_name is None or child_type_name == "":
            effects.append(ErrorEffect(
                issue_id=event.issue_id,
                message=f"No type for child '{key}': decompose rule has no child_type and worker didn't specify one",
            ))
            return

        if child_type_name not in config.types:
            effects.append(ErrorEffect(
                issue_id=event.issue_id,
                message=f"Unknown type '{child_type_name}' for child '{key}'",
            ))
            return

        child_type_def = config.get_type(child_type_name)

        raw_depends: list[str] = sub.get("depends_on", [])
        resolved_depends: list[str] = []
        for dep_key in raw_depends:
            if dep_key in key_to_id:
                resolved_depends.append(key_to_id[dep_key])

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
        append_log(child, ts, "created", {"state": child_type_def.initial})

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
```

- [ ] **Step 6: Update `_find_decompose_rule`**

This needs the issue type to find the right state:

```python
def _find_decompose_rule(config: StateMachineConfig, type_name: str, state_name: str) -> OnDecompose | None:
    state_def = config.types.get(type_name, TypeDef(fields={}, initial="", states={})).states.get(state_name)
    if state_def is None:
        return None
    for rule in state_def.on.values():
        if isinstance(rule, OnDecompose):
            return rule
    return None
```

- [ ] **Step 7: Update `_cascading_unblock`**

Use issue type for state lookups:

```python
def _cascading_unblock(config, state, terminal_issue_id, effects, ts):
    terminal_issue = state.issues[terminal_issue_id]

    if terminal_issue.decomposed_from is not None:
        parent_id = terminal_issue.decomposed_from
        parent = state.issues[parent_id]
        children = get_children(state, parent_id)
        all_terminal = all(
            config.get_state(state.issues[cid].type, state.issues[cid].state).terminal
            for cid in children
        )
        if all_terminal and not parent.worker_active:
            append_log(parent, ts, "unblocked", {"reason": "decomposition"})
            decompose_rule = _find_decompose_rule(config, parent.type, parent.state)
            if decompose_rule is not None and decompose_rule.then is not None:
                old_state = parent.state
                _apply_transition(config, state, parent_id, parent, old_state, decompose_rule.then, effects, ts)
            else:
                prev_len = len(effects)
                try_dispatch(config, state, parent_id, effects)
                if len(effects) > prev_len:
                    append_log(parent, ts, "worker_dispatched", {"state": parent.state})

    for iid, iss in state.issues.items():
        if terminal_issue_id in iss.depends_on:
            all_deps_terminal = all(
                config.get_state(state.issues[dep_id].type, state.issues[dep_id].state).terminal
                for dep_id in iss.depends_on
            )
            if (
                all_deps_terminal
                and not is_blocked(state, config, iid)
                and not iss.worker_active
                and config.get_state(iss.type, iss.state).worker is not None
            ):
                append_log(iss, ts, "unblocked", {"reason": "dependency"})
                prev_len = len(effects)
                try_dispatch(config, state, iid, effects)
                if len(effects) > prev_len:
                    append_log(iss, ts, "worker_dispatched", {"state": iss.state})
```

- [ ] **Step 8: Update `_handle_worker_failed`**

Replace `config.states[issue.state]` with `config.get_state(issue.type, issue.state)`.

Replace `config.issue_fields` with `config.get_type(issue.type).fields` for the `failure_context` field check.

Update the retry dispatch to include `issue_type`:

```python
    effects.append(
        DispatchWorkerEffect(
            issue_id=event.issue_id,
            issue_type=issue.type,
            state=issue.state,
            result_format=build_result_format(config, issue.type, issue.state),
            issue=build_issue_context(state, event.issue_id),
        )
    )
```

- [ ] **Step 9: Run type checker**

Run: `uv run mypy src/orca/engine/reducer.py`
Expected: PASS (no type errors)

- [ ] **Step 10: Commit**

```bash
git add src/orca/engine/reducer.py
git commit -m "feat: type-aware reducer with typed decomposition"
```

---

### Task 6: Update conftest fixtures and all engine tests

**Files:**
- Modify: `tests/engine/conftest.py`
- Modify: All `tests/engine/test_*.py` files

All test configs use legacy format and will be auto-wrapped as `type: "default"`. But all Issue construction in tests must include `type="default"`. Every direct `config.states[...]` or `config.initial` access must be updated.

- [ ] **Step 1: Update conftest.py fixtures**

No changes needed to the YAML fixtures themselves — `_parse_legacy_config` wraps them. But verify they still parse correctly.

- [ ] **Step 2: Update test_reducer_create.py**

Add `type="default"` to all Issue constructions. Update `config.states[...]` to `config.get_state("default", ...)` or `config.types["default"].states[...]`.

- [ ] **Step 3: Update test_reducer_advance.py**

Same pattern.

- [ ] **Step 4: Update test_reducer_worker_result.py**

Same pattern.

- [ ] **Step 5: Update test_reducer_worker_failed.py**

Same pattern.

- [ ] **Step 6: Update test_scenario_decompose.py**

Issues created by decompose will have `type="default"` (since legacy configs have no `child_type` on `OnDecompose`). Update assertions to check `issue.type == "default"`.

- [ ] **Step 7: Update test_scenario_pipeline.py, test_scenario_kanban.py, test_scenario_edge_cases.py, test_scenario_queuing.py**

Same pattern — add `type` to Issues, update config lookups.

- [ ] **Step 8: Update test_hop_limits.py, test_event_log.py, test_dispatch.py, test_formatting.py, test_types.py, test_scenario_serialization.py**

Same pattern.

- [ ] **Step 9: Run all engine tests**

Run: `uv run pytest tests/engine/ -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add tests/engine/
git commit -m "test: update all engine tests for typed config shape"
```

---

### Task 7: Update formatting.py to show type:state

**Files:**
- Modify: `src/orca/engine/formatting.py`
- Test: `tests/engine/test_formatting.py`

- [ ] **Step 1: Write failing test**

In `tests/engine/test_formatting.py`, add:

```python
class TestTypedFormatting:
    def test_shows_type_and_state(self) -> None:
        """When type is not 'default', display [type:state]."""
        # Build a typed config and state with an epic issue
        # ... (construct config with TypeDef for "epic")
        issue = Issue(
            type="epic",
            fields={"title": "Big task"},
            state="scoping",
            worker_active=True,
            decomposed_from=None,
            depends_on=[],
            event_log=[EventLogEntry(timestamp="2026-01-01T00:00:00Z", type="created", data={"state": "scoping"})],
        )
        state = State(issues={"ROOT": issue}, worker_queues={})
        output = format_issues(state, config, "2026-01-01T01:00:00Z")
        assert "[epic:scoping]" in output

    def test_default_type_shows_state_only(self) -> None:
        """Legacy configs with type='default' show just [state]."""
        # ... construct issue with type="default"
        output = format_issues(state, config, "2026-01-01T01:00:00Z")
        assert "[scoping]" in output
        assert "[default:" not in output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_formatting.py::TestTypedFormatting -v`
Expected: FAIL

- [ ] **Step 3: Update formatting.py**

In `_render_issue`, update state label:

```python
    state_def = config.get_state(issue.type, issue.state)
    is_terminal = state_def.terminal

    # Show [type:state] unless type is "default"
    if issue.type == "default":
        state_label = f"[{issue.state}]"
    else:
        state_label = f"[{issue.type}:{issue.state}]"

    marker = "" if is_terminal else " ..."
    line = f"{prefix}{connector}{issue_id} {state_label}{marker} {elapsed}"
```

Same change in the root rendering section of `format_issues`.

Update the worker queue section — queue keys are now `"{type}:{state}"`:

```python
    for queue_key in sorted(state.worker_queues.keys()):
        queue = state.worker_queues[queue_key]
        if queue:
            lines.append(f"Queued in '{queue_key}': {', '.join(queue)}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_formatting.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/engine/formatting.py tests/engine/test_formatting.py
git commit -m "feat: formatting shows [type:state] for typed issues"
```

---

### Task 8: Update orchestrator.py for typed effects

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py`

- [ ] **Step 1: Update `_is_terminal` to use issue type**

```python
    def _is_terminal(self, issue_id: str) -> bool:
        issue = self.state.issues.get(issue_id)
        if issue is None:
            return False
        state_def = self.config.types.get(issue.type, TypeDef(fields={}, initial="", states={})).states.get(issue.state)
        if state_def is None:
            return False
        return state_def.terminal
```

- [ ] **Step 2: Update `_spawn_worker` to use `effect.issue_type`**

```python
    def _spawn_worker(self, effect: DispatchWorkerEffect) -> None:
        state_def = self.config.get_state(effect.issue_type, effect.state)
        # ... rest uses state_def.worker as before
```

- [ ] **Step 3: Update `_process_retry_signals`**

The retry code builds `DispatchWorkerEffect` manually — add `issue_type`:

```python
            pending.append(
                DispatchWorkerEffect(
                    issue_id=issue_id,
                    issue_type=issue.type,
                    state=issue.state,
                    result_format=build_result_format(self.config, issue.type, issue.state),
                    issue=build_issue_context(self.state, issue_id),
                )
            )
```

- [ ] **Step 4: Run type checker on orchestrator**

Run: `uv run mypy src/orca/orchestrator/orchestrator.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py
git commit -m "feat: orchestrator uses issue_type from effects"
```

---

### Task 9: Update runner.py for typed config

**Files:**
- Modify: `src/orca/orchestrator/runner.py`

- [ ] **Step 1: Update `_recover_effects` for type-aware lookups**

Replace `config.states.get(issue.state)` with `config.types.get(issue.type, ...)...`:

```python
    for issue_id, issue in state.issues.items():
        type_def = config.types.get(issue.type)
        if type_def is None:
            continue
        state_def = type_def.states.get(issue.state)
        if state_def is None or state_def.terminal:
            continue
        # ...
        result_format = build_result_format(config, issue.type, issue.state)
        # ...
        recovered_effects.append(
            DispatchWorkerEffect(
                issue_id=issue_id,
                issue_type=issue.type,
                state=issue.state,
                result_format=result_format,
                issue=issue_context,
            )
        )
```

- [ ] **Step 2: Run type checker**

Run: `uv run mypy src/orca/orchestrator/runner.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "feat: runner uses type-aware config lookups"
```

---

### Task 10: Update orchestrator tests

**Files:**
- Modify: `tests/orchestrator/test_orchestrator.py`
- Modify: `tests/orchestrator/test_runner.py`
- Modify: `tests/orchestrator/test_worker.py`
- Modify: `tests/orchestrator/test_persistence.py`
- Modify: Other orchestrator tests that construct State/Issue/Config objects

- [ ] **Step 1: Add `type` field to all Issue constructions in orchestrator tests**

Every `Issue(fields=..., state=..., ...)` must become `Issue(type="default", fields=..., state=..., ...)`.

Every `DispatchWorkerEffect(issue_id=..., state=..., ...)` must become `DispatchWorkerEffect(issue_id=..., issue_type="default", state=..., ...)`.

Every `StateMachineConfig(issue_fields=..., initial=..., states=...)` must be replaced with the new shape using `TypeDef`.

- [ ] **Step 2: Run all orchestrator tests**

Run: `uv run pytest tests/orchestrator/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/
git commit -m "test: update orchestrator tests for typed config shape"
```

---

### Task 11: Update TUI tests

**Files:**
- Modify: `tests/tui/test_*.py` — any tests that construct Issue/State/Config objects

- [ ] **Step 1: Add `type` field to all Issue constructions in TUI tests**

Same mechanical change as Task 10.

- [ ] **Step 2: Run all TUI tests**

Run: `uv run pytest tests/tui/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/tui/
git commit -m "test: update TUI tests for typed config shape"
```

---

### Task 12: Add typed decomposition scenario test

**Files:**
- Create: `tests/engine/test_scenario_typed_decompose.py`

End-to-end test: epic decomposes into tasks with a different flow, tasks complete, parent unblocks.

- [ ] **Step 1: Write the scenario test**

```python
"""Typed decomposition scenario: epic -> task with different flows."""
from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    State,
    WorkerResultEvent,
)

TYPED_CONFIG = """\
root_type: epic
max_hops: 20

types:
  epic:
    fields:
      title: {type: string, description: Title}
      scope: {type: string, description: Scope}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scope.md
          result_format:
            outcome:
              type: enum
              values: [ready, decompose]
              description: d
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
              description: s
        on:
          ready: done
          decompose:
            action: decompose
            child_type: task
            then: done
      done:
        terminal: true

  task:
    fields:
      title: {type: string, description: Title}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/impl.md
          result_format:
            outcome:
              type: enum
              values: [done]
              description: d
        on:
          done: done
      done:
        terminal: true
"""

TS = "2026-01-01T00:00:00Z"


def _clock(value: str = TS) -> Callable[[], str]:
    return lambda: value


def _counter() -> Callable[[], str]:
    n = 0
    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"
    return gen


class TestTypedDecomposition:
    def test_epic_decomposes_into_tasks_with_different_flow(self) -> None:
        config = parse_config(TYPED_CONFIG)
        gen = _counter()
        state = State(issues={}, worker_queues={})

        # Create epic
        state, effects = reduce(
            config, state,
            CreateEvent(issue_id="EPIC-1", fields={"title": "Big feature", "scope": "all"}, timestamp=TS),
            gen, _clock(),
        )
        assert state.issues["EPIC-1"].type == "epic"
        assert state.issues["EPIC-1"].state == "scoping"
        assert len([e for e in effects if isinstance(e, DispatchWorkerEffect)]) == 1

        # Epic decomposes into 2 tasks
        state, effects = reduce(
            config, state,
            WorkerResultEvent(
                issue_id="EPIC-1",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "api", "fields": {"title": "Build API"}},
                        {"key": "ui", "fields": {"title": "Build UI"}},
                    ],
                },
                timestamp=TS,
            ),
            gen, _clock(),
        )

        # Epic moves to done (then: done)
        assert state.issues["EPIC-1"].state == "done"

        # Children are tasks starting at implementing (not scoping!)
        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "EPIC-1"]
        assert len(child_ids) == 2
        for cid in child_ids:
            assert state.issues[cid].type == "task"
            assert state.issues[cid].state == "implementing"
            assert state.issues[cid].worker_active is True

        # Complete both tasks
        for cid in child_ids:
            state, _ = reduce(
                config, state,
                WorkerResultEvent(issue_id=cid, result={"outcome": "done"}, timestamp=TS),
                gen, _clock(),
            )
            assert state.issues[cid].state == "done"

    def test_worker_overrides_child_type(self) -> None:
        config = parse_config(TYPED_CONFIG)
        gen = _counter()
        state = State(issues={}, worker_queues={})

        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="EPIC-1", fields={"title": "Feature", "scope": "all"}, timestamp=TS),
            gen, _clock(),
        )

        # Worker overrides one child to be an epic (recursive decomposition)
        state, _ = reduce(
            config, state,
            WorkerResultEvent(
                issue_id="EPIC-1",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "sub-epic", "type": "epic", "fields": {"title": "Sub-epic", "scope": "sub"}},
                        {"key": "task", "fields": {"title": "Simple task"}},
                    ],
                },
                timestamp=TS,
            ),
            gen, _clock(),
        )

        children = {
            state.issues[iid].fields["title"]: state.issues[iid]
            for iid in state.issues
            if state.issues[iid].decomposed_from == "EPIC-1"
        }
        assert children["Sub-epic"].type == "epic"
        assert children["Sub-epic"].state == "scoping"
        assert children["Simple task"].type == "task"
        assert children["Simple task"].state == "implementing"

    def test_missing_child_type_errors(self) -> None:
        """If decompose rule has no child_type and worker doesn't specify, error."""
        no_child_type_config = """\
root_type: epic
types:
  epic:
    fields:
      title: {type: string, description: Title}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: p.md
          result_format:
            outcome:
              type: enum
              values: [decompose]
              description: d
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
              description: s
        on:
          decompose:
            action: decompose
      done:
        terminal: true
"""
        config = parse_config(no_child_type_config)
        gen = _counter()
        state = State(issues={}, worker_queues={})

        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="E1", fields={"title": "X"}, timestamp=TS),
            gen, _clock(),
        )

        state, effects = reduce(
            config, state,
            WorkerResultEvent(
                issue_id="E1",
                result={"outcome": "decompose", "sub_issues": [{"key": "a", "fields": {"title": "A"}}]},
                timestamp=TS,
            ),
            gen, _clock(),
        )

        from orca.engine.types import ErrorEffect
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) >= 1
        assert "type" in error_effects[0].message.lower() or "child_type" in error_effects[0].message.lower()
```

- [ ] **Step 2: Run the scenario test**

Run: `uv run pytest tests/engine/test_scenario_typed_decompose.py -v`
Expected: ALL PASS (implementation was done in earlier tasks)

- [ ] **Step 3: Commit**

```bash
git add tests/engine/test_scenario_typed_decompose.py
git commit -m "test: add typed decomposition scenario tests"
```

---

### Task 13: Update example orca.yml

**Files:**
- Modify: `example/orca.yml`

- [ ] **Step 1: Convert to typed format**

Wrap the existing config in a `types.default` block with `root_type: default`. This maintains the current behavior while demonstrating the new format.

```yaml
root_type: default
max_hops: 15

types:
  default:
    fields:
      title:
        type: string
        description: "Short title for the issue"
      description:
        type: string
        description: "Detailed description of what needs to be done"
      scope_boundary:
        type: string
        description: "Files and directories this issue owns"
    initial: scoping
    states:
      scoping:
        # ... (same as before, but add child_type: default to decompose rule)
      planning:
        # ... (same as before)
      implementing:
        # ... (same as before)
      applying:
        # ... (same as before)
      done:
        terminal: true
```

- [ ] **Step 2: Verify config parses**

Run: `uv run python -c "from orca.engine.config import parse_config; parse_config(open('example/orca.yml').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add example/orca.yml
git commit -m "docs: convert example orca.yml to typed format"
```

---

### Task 14: Full lint, type-check, and test pass

- [ ] **Step 1: Run ruff lint**

Run: `uv run ruff check .`
Expected: PASS

- [ ] **Step 2: Run ruff format check**

Run: `uv run ruff format --check .`
Expected: PASS

- [ ] **Step 3: Run mypy**

Run: `uv run mypy src/`
Expected: PASS

- [ ] **Step 4: Run all tests**

Run: `uv run pytest`
Expected: ALL PASS

- [ ] **Step 5: Fix any failures and commit**

```bash
git add -A
git commit -m "fix: resolve lint/type/test issues from typed issue flows"
```
