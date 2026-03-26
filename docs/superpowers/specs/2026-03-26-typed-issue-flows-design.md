# Typed Issue Flows

## Problem

All issues — including children from decomposition — follow the same state machine flow. When an epic decomposes into subtasks, those subtasks pass through stages (e.g. scoping, planning) that the parent already completed. This is wasteful and sometimes wrong — different kinds of work need different flows.

## Solution

Introduce **issue types**. Each type defines its own fields schema, initial state, and state machine. Decomposition rules specify what type children should be, and workers can override the type per-child.

## Config Structure

The top-level orca.yml changes from a single implicit type to a `types` map plus a `root_type`:

```yaml
root_type: epic
max_hops: 15
max_worker_retries: 5

types:
  epic:
    fields:
      title: {type: string}
      description: {type: string}
      scope_boundary: {type: string}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scope.md
          result_format:
            outcome: {type: enum, values: [ready, decompose]}
            sub_issues: {type: list, required_when: [decompose]}
        on:
          ready: planning
          decompose:
            action: decompose
            child_type: task
            then: integrating
      planning: ...
      integrating:
        worker: {kind: claude-code, prompt: prompts/integrate.md}
        on:
          done: done
      done: {terminal: true}

  task:
    fields:
      title: {type: string}
      description: {type: string}
    initial: implementing
    states:
      implementing: ...
      applying: ...
      done: {terminal: true}

  subtask:
    fields:
      title: {type: string}
      description: {type: string}
    initial: coding
    states:
      coding: ...
      done: {terminal: true}
```

- `root_type` determines the type of the issue created by the initial `CreateEvent`
- Each type is fully self-contained: own fields, own initial state, own state machine
- `child_type` on decompose rules sets the default type for children
- Workers can override the type per-child in their result

## Type-Aware Issue Model

The `Issue` dataclass gains a `type` field:

```python
@dataclass
class Issue:
    type: str                        # e.g. "epic", "task", "subtask"
    fields: dict[str, Any]
    state: str
    worker_active: bool
    decomposed_from: str | None
    depends_on: list[str]
    event_log: list[EventLogEntry]
    visit_counts: dict[str, int]
    hop_count: int
    failure_count: int
```

Every reducer lookup that currently does `config.states[issue.state]` becomes `config.types[issue.type].states[issue.state]`:

```python
# Before
state_def = config.states[issue.state]
initial = config.initial

# After
type_def = config.types[issue.type]
state_def = type_def.states[issue.state]
initial = type_def.initial
```

`CreateEvent` uses `config.root_type` for top-level issues. Decomposition uses the child's assigned type.

Fields are validated against `config.types[type].fields` at issue creation time (both top-level and children).

## Decomposition With Types

Worker result format gains an optional `type` per child:

```json
{
  "outcome": "decompose",
  "sub_issues": [
    {"key": "api", "fields": {"title": "Build API"}, "depends_on": []},
    {"key": "db", "type": "subtask", "fields": {"title": "Setup DB"}, "depends_on": []}
  ]
}
```

- `type` is optional — defaults to `child_type` from the decompose rule
- If provided, overrides the default

In `_apply_decompose`:

```python
decompose_rule = state_def.on[outcome]  # OnDecompose
default_child_type = decompose_rule.child_type

for sub in result["sub_issues"]:
    child_type = sub.get("type", default_child_type)

    # Validate type exists
    if child_type not in config.types:
        # ErrorEffect — unknown type

    type_def = config.types[child_type]

    # Validate child fields against type's field schema
    validate_fields(sub["fields"], type_def.fields)

    # Create issue with type's initial state
    child = Issue(
        type=child_type,
        fields=sub["fields"],
        state=type_def.initial,
        ...
    )
```

Validation rules:
- `child_type` in decompose rule must reference an existing type
- Worker-provided `type` override must also exist in config
- If neither the decompose rule has `child_type` nor the worker provides `type` for a child, emit an ErrorEffect (no implicit default)
- Child fields validated against the target type's field schema, not the parent's

## Config Data Model

```python
@dataclass
class TypeDef:
    fields: dict[str, FieldDef]
    initial: str
    states: dict[str, StateDef]

@dataclass
class StateMachineConfig:
    root_type: str
    types: dict[str, TypeDef]
    max_hops: int
    max_worker_retries: int
```

### Config Validation (at load time)

1. `root_type` must exist in `types`
2. For each type:
   - `initial` must reference a state within that type's `states`
   - Each state's `on` transitions must reference states within the same type (no cross-type transitions)
   - Each `on.decompose.child_type` must reference an existing type in `types`
   - At least one terminal state must exist
3. No circular type decomposition without a terminal escape path

This is a breaking config change. Existing single-type orca.yml files must be wrapped in a `types` block. Acceptable given the project is pre-1.0.

## Dispatch and Queueing

`max_workers` becomes scoped per `(type, state)` pair. Two types sharing a state name (e.g. both have `done`) are independent:

```python
# Before
worker_queues: dict[str, list[str]]                # state_name -> [issue_ids]

# After
worker_queues: dict[tuple[str, str], list[str]]    # (type, state) -> [issue_ids]
```

This prevents a `task` in `implementing` from being blocked by an unrelated `subtask` in its own `implementing` state.

## DispatchWorkerEffect

The effect gains `issue_type` so the orchestrator knows which prompt template to render:

```python
@dataclass
class DispatchWorkerEffect:
    issue_id: str
    issue_type: str          # new
    state: str
    result_format: dict
    issue: dict
```

## Formatting

The ASCII tree shows issue type alongside state:

```
ROOT-1 [epic:scoping] ... 2h 15m
├── CHILD-1 [task:done] 20m
├── CHILD-2 [task:implementing] ... 1h 30m
└── CHILD-3 [subtask:coding] ... 45m
```

## Testing Strategy

### Engine tests (unit, pure)

- **Config validation:** Multi-type configs parse correctly; invalid configs (missing type refs, cross-type transitions, missing child_type) raise clear errors
- **Reducer:** Create with root_type, decompose producing typed children, type override per-child, field validation against type schema
- **Dispatch:** Queue keys are `(type, state)`, max_workers scoped per type
- **Cascading unblock:** Parent (epic) unblocks when typed children (task) all reach their own terminal states
- **Hop/visit limits:** Counted per-issue as today, unaffected by types

### Integration tests (orchestrator)

- End-to-end: epic decomposes into tasks with different flows, both complete, parent unblocks
- Worker type override: one child gets a different type than the default
- Error cases: worker returns unknown type, fields don't match target type schema

No changes needed to worktree, persistence, or worker protocol tests — those layers are type-agnostic.
