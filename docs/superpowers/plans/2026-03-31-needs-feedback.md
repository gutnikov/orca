# Needs Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow any worker to request user clarification via Slack by returning `needs_feedback`, triggering a feedback agent that conducts a multi-turn conversation and re-dispatches the original worker with answers.

**Architecture:** Engine-level reserved outcome handled in the reducer. New `DispatchFeedbackAgentEffect` and `FeedbackReceivedEvent` types. Orchestrator spawns a real Claude Code feedback agent with Slack HITL MCP access. Re-dispatch merges conversation into issue fields.

**Tech Stack:** Python 3.12, pure engine (reducer/types), async orchestrator, Jinja2 prompts, Slack HITL MCP

---

### Task 1: Add Engine Types

**Files:**
- Modify: `src/orca/engine/types.py:206-227`
- Test: `tests/engine/test_types_feedback.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_types_feedback.py
from __future__ import annotations

from orca.engine.types import (
    DispatchFeedbackAgentEffect,
    Effect,
    Event,
    FeedbackReceivedEvent,
)


class TestFeedbackTypes:
    def test_dispatch_feedback_agent_effect_fields(self) -> None:
        effect = DispatchFeedbackAgentEffect(
            issue_id="issue-1",
            issue_type="default",
            state="implementing",
            questions="Which API should we target?",
            issue={"title": "Fix bug"},
        )
        assert effect.issue_id == "issue-1"
        assert effect.questions == "Which API should we target?"

    def test_dispatch_feedback_agent_effect_is_effect(self) -> None:
        effect = DispatchFeedbackAgentEffect(
            issue_id="issue-1",
            issue_type="default",
            state="implementing",
            questions="Q?",
            issue={},
        )
        assert isinstance(effect, DispatchFeedbackAgentEffect)
        # Verify it's part of the Effect union (type-checker enforces this,
        # but we can verify it's accepted where Effect is expected)
        effects: list[Effect] = [effect]
        assert len(effects) == 1

    def test_feedback_received_event_fields(self) -> None:
        event = FeedbackReceivedEvent(
            issue_id="issue-1",
            feedback_context="User said: use REST API",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert event.issue_id == "issue-1"
        assert event.feedback_context == "User said: use REST API"
        assert event.timestamp == "2026-01-01T00:00:00Z"

    def test_feedback_received_event_is_event(self) -> None:
        event = FeedbackReceivedEvent(
            issue_id="issue-1",
            feedback_context="answer",
            timestamp="2026-01-01T00:00:00Z",
        )
        events: list[Event] = [event]
        assert len(events) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_types_feedback.py -v`
Expected: FAIL with `ImportError: cannot import name 'DispatchFeedbackAgentEffect'`

- [ ] **Step 3: Add the new types to `types.py`**

After the existing `WorkerFailedEvent` and before the `Event` union, add:

```python
@dataclass(frozen=True)
class FeedbackReceivedEvent:
    issue_id: str
    feedback_context: str
    timestamp: str
```

Update the `Event` union:

```python
Event = CreateEvent | AdvanceEvent | WorkerResultEvent | WorkerFailedEvent | FeedbackReceivedEvent
```

After the existing `ErrorEffect` and before the `Effect` union, add:

```python
@dataclass(frozen=True)
class DispatchFeedbackAgentEffect:
    issue_id: str
    issue_type: str
    state: str
    questions: str
    issue: dict[str, Any]
```

Update the `Effect` union:

```python
Effect = DispatchWorkerEffect | ErrorEffect | DispatchFeedbackAgentEffect
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_types_feedback.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Run full lint and type-check**

Run: `uv run ruff check src/orca/engine/types.py && uv run mypy src/orca/engine/types.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/engine/test_types_feedback.py src/orca/engine/types.py
git commit -m "feat(engine): add DispatchFeedbackAgentEffect and FeedbackReceivedEvent types"
```

---

### Task 2: Config Validator — Allow `needs_feedback` Without `on:` Rule

**Files:**
- Modify: `src/orca/engine/config.py:227-234`
- Test: `tests/engine/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/engine/test_config.py`:

```python
class TestNeedsFeedbackValidation:
    """needs_feedback in outcome values should not require a matching on: rule."""

    def test_needs_feedback_outcome_without_on_rule_is_valid(self) -> None:
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: Issue title

states:
  working:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - done
            - needs_feedback
          description: Outcome
        feedback_questions:
          type: string
          description: Questions for user
          required_when: needs_feedback
    on:
      done: finished

  finished:
    terminal: true

initial: working
"""
        config = parse_config(yaml_str)
        outcome = config.types["default"].states["working"].worker
        assert outcome is not None
        assert "needs_feedback" in outcome.result_format["outcome"].values  # type: ignore[union-attr]

    def test_needs_feedback_only_outcome_is_invalid(self) -> None:
        """A state with ONLY needs_feedback and no real on: rules is invalid (no way to progress)."""
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: Issue title

states:
  working:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - needs_feedback
          description: Outcome
        feedback_questions:
          type: string
          description: Questions
          required_when: needs_feedback
    on: {}

  done:
    terminal: true

initial: working
"""
        with pytest.raises(ConfigValidationError):
            parse_config(yaml_str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_config.py::TestNeedsFeedbackValidation -v`
Expected: First test FAILS with `ConfigValidationError` (validator rejects `needs_feedback` because it has no `on:` rule)

- [ ] **Step 3: Update config validator**

In `src/orca/engine/config.py`, add a constant near the top of the file (after imports):

```python
# Reserved outcome handled by the engine — does not require an on: rule.
_RESERVED_OUTCOMES = frozenset({"needs_feedback"})
```

In the validation loop (~line 228), where it checks that every `on:` key matches an outcome value, skip reserved outcomes:

Change the block at lines 228-234 from:

```python
                # Rule 3: every on key matches a value in outcome.values
                for key in state.on:
                    if key not in outcome.values:
```

to:

```python
                # Rule 3: every on key matches a value in outcome.values
                for key in state.on:
                    if key not in outcome.values and key not in _RESERVED_OUTCOMES:
```

And add a new check after that block — validate that not ALL outcomes are reserved (the state must have at least one real transition):

```python
                # Rule 3b: needs_feedback doesn't need an on: rule, but at least
                # one non-reserved outcome must have a matching on: rule
                real_outcomes = [v for v in outcome.values if v not in _RESERVED_OUTCOMES]
                if not real_outcomes:
                    msg = (
                        f"Type '{type_name}', state '{name}' has only reserved outcomes "
                        f"— at least one non-reserved outcome with an on: rule is required"
                    )
                    raise ConfigValidationError(msg)
                for val in real_outcomes:
                    if val not in state.on:
                        msg = (
                            f"Type '{type_name}', outcome value '{val}' in state '{name}' "
                            f"has no matching on: rule"
                        )
                        raise ConfigValidationError(msg)
```

Wait — the existing validator does NOT check that outcome values have matching on: keys (it only checks the reverse: on: keys must be in outcome values). So we only need the `_RESERVED_OUTCOMES` skip in the existing check and the "at least one real outcome" guard. No need to add per-value checks.

Simplified change — in the block at lines 228-234, update to:

```python
                # Rule 3: every on key matches a value in outcome.values
                for key in state.on:
                    if key not in outcome.values:
                        msg = (
                            f"Type '{type_name}', on key '{key}' in state '{name}' "
                            f"does not match any outcome value ({outcome.values})"
                        )
                        raise ConfigValidationError(msg)

                # Rule 3b: at least one non-reserved outcome must exist
                real_outcomes = [v for v in outcome.values if v not in _RESERVED_OUTCOMES]
                if not real_outcomes:
                    msg = (
                        f"Type '{type_name}', state '{name}' has only reserved outcomes "
                        f"— at least one non-reserved outcome with an on: rule is required"
                    )
                    raise ConfigValidationError(msg)
```

Note: the existing check (on key must be in outcome.values) doesn't need changes — `needs_feedback` is never added to `on:`, so it won't trigger. The only change is adding Rule 3b after the existing Rule 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_config.py::TestNeedsFeedbackValidation -v`
Expected: PASS (both tests)

- [ ] **Step 5: Run existing config tests to verify no regressions**

Run: `uv run pytest tests/engine/test_config.py -v`
Expected: All existing tests PASS

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src/orca/engine/config.py && uv run mypy src/orca/engine/config.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/engine/config.py tests/engine/test_config.py
git commit -m "feat(config): allow needs_feedback in outcome values without on: rule"
```

---

### Task 3: Reducer — Handle `needs_feedback` Outcome

**Files:**
- Modify: `src/orca/engine/reducer.py:1-54` (imports and reduce function)
- Modify: `src/orca/engine/reducer.py:170-224` (_handle_worker_result)
- Test: `tests/engine/test_reducer_feedback.py` (new)

- [ ] **Step 1: Add fixture to conftest**

Append to `tests/engine/conftest.py`:

```python
@pytest.fixture()
def feedback_config_yaml() -> str:
    return """\
issue:
  fields:
    title:
      type: string
      description: Issue title

states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - complete
            - needs_feedback
          description: Implementation outcome
        feedback_questions:
          type: string
          description: Questions for user
          required_when: needs_feedback
    on:
      complete: done

  done:
    terminal: true

initial: implementing

max-retries: 3
"""
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/engine/test_reducer_feedback.py
from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchFeedbackAgentEffect,
    DispatchWorkerEffect,
    ErrorEffect,
    FeedbackReceivedEvent,
    State,
    WorkerResultEvent,
)


def _counter() -> Callable[[], str]:
    n = 0

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"id-{n}"

    return next_id


def _clock(value: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: value


def _setup(yaml: str) -> tuple[object, State]:
    """Create config and state with one issue in initial state with worker_active=True."""
    from orca.engine.types import StateMachineConfig

    config = parse_config(yaml)
    assert isinstance(config, StateMachineConfig)
    state = State(issues={}, worker_queues={})
    state, _ = reduce(
        config,
        state,
        CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
        _counter(),
        _clock(),
    )
    return config, state


class TestNeedsFeedbackOutcome:
    def test_needs_feedback_emits_dispatch_feedback_effect(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        assert state.issues["A"].worker_active is True

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Which API?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        feedback_effects = [e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]
        assert len(feedback_effects) == 1
        assert feedback_effects[0].issue_id == "A"
        assert feedback_effects[0].questions == "Which API?"
        assert feedback_effects[0].state == "implementing"

    def test_needs_feedback_clears_worker_active(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        assert state.issues["A"].worker_active is False

    def test_needs_feedback_increments_failure_count(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        assert state.issues["A"].failure_count == 0

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        assert state.issues["A"].failure_count == 1

    def test_needs_feedback_stores_questions_in_fields(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Which API?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        assert state.issues["A"].fields["feedback_questions"] == "Which API?"

    def test_needs_feedback_logs_worker_result(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        result_entries = [e for e in state.issues["A"].event_log if e.type == "worker_result"]
        assert len(result_entries) == 1
        assert result_entries[0].data["outcome"] == "needs_feedback"

    def test_needs_feedback_exhausted_retries_emits_error(self, feedback_config_yaml: str) -> None:
        """When failure_count >= max_worker_retries, needs_feedback should not spawn feedback agent."""
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        # Manually set failure_count to max_retries - 1 (will increment to max)
        state.issues["A"].failure_count = 2  # max is 3, will become 3

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        feedback_effects = [e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]
        assert len(feedback_effects) == 0
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "retries exhausted" in error_effects[0].message

    def test_needs_feedback_does_not_change_state(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        assert state.issues["A"].state == "implementing"


class TestFeedbackReceivedEvent:
    def test_feedback_received_stores_context_and_redispatches(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        # Worker returns needs_feedback
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )
        assert state.issues["A"].worker_active is False

        # Feedback received
        state, effects = reduce(
            config,
            state,
            FeedbackReceivedEvent(
                issue_id="A",
                feedback_context="User said: use REST",
                timestamp="2026-01-01T00:02:00Z",
            ),
            _counter(),
            _clock(),
        )

        assert state.issues["A"].fields["feedback_context"] == "User said: use REST"
        assert state.issues["A"].worker_active is True

        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1
        assert dispatch_effects[0].issue_id == "A"
        assert dispatch_effects[0].state == "implementing"

    def test_feedback_received_logs_event(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        state, _ = reduce(
            config,
            state,
            FeedbackReceivedEvent(
                issue_id="A",
                feedback_context="answer",
                timestamp="2026-01-01T00:02:00Z",
            ),
            _counter(),
            _clock(),
        )

        fb_entries = [e for e in state.issues["A"].event_log if e.type == "feedback_received"]
        assert len(fb_entries) == 1

    def test_feedback_received_nonexistent_issue_emits_error(self, feedback_config_yaml: str) -> None:
        config = parse_config(feedback_config_yaml)
        state = State(issues={}, worker_queues={})

        state, effects = reduce(
            config,
            state,
            FeedbackReceivedEvent(
                issue_id="NOPE",
                feedback_context="answer",
                timestamp="2026-01-01T00:02:00Z",
            ),
            _counter(),
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1

    def test_feedback_received_when_worker_active_emits_error(self, feedback_config_yaml: str) -> None:
        """Feedback should only arrive when worker_active is False (between dispatches)."""
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        # worker_active is True (worker just dispatched)
        assert state.issues["A"].worker_active is True

        state, effects = reduce(
            config,
            state,
            FeedbackReceivedEvent(
                issue_id="A",
                feedback_context="answer",
                timestamp="2026-01-01T00:02:00Z",
            ),
            _counter(),
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_reducer_feedback.py -v`
Expected: FAIL — `needs_feedback` outcome hits the `outcome not in state_def.on` check and emits `ErrorEffect`

- [ ] **Step 4: Update reducer imports**

In `src/orca/engine/reducer.py`, update imports to include the new types:

```python
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchFeedbackAgentEffect,
    DispatchWorkerEffect,
    Effect,
    ErrorEffect,
    Event,
    FeedbackReceivedEvent,
    Issue,
    OnDecompose,
    OnTransition,
    State,
    StateMachineConfig,
    WorkerFailedEvent,
    WorkerResultEvent,
)
```

- [ ] **Step 5: Add `needs_feedback` handling in `_handle_worker_result`**

In `_handle_worker_result`, after line 216 (`outcome = event.result.get("outcome")`) and before line 217 (`if outcome is None or outcome not in state_def.on:`), insert the needs_feedback branch:

```python
    # Reserved outcome: needs_feedback — handled before on: rule lookup
    if outcome == "needs_feedback":
        _handle_needs_feedback(config, state, event, issue, effects, ts)
        return
```

Then change line 217 from:

```python
    if outcome is None or outcome not in state_def.on:
```

to (no change needed — the early return above means `needs_feedback` never reaches this check).

- [ ] **Step 6: Implement `_handle_needs_feedback` function**

Add after `_handle_worker_result`:

```python
def _handle_needs_feedback(
    config: StateMachineConfig,
    state: State,
    event: WorkerResultEvent,
    issue: Issue,
    effects: list[Effect],
    ts: str,
) -> None:
    """Handle the reserved needs_feedback outcome: store questions, emit feedback agent dispatch."""
    questions = str(event.result.get("feedback_questions", ""))

    # Clear worker slot and increment failure count
    issue.worker_active = False
    issue.failure_count += 1

    # Log the result
    append_log(issue, event.timestamp, "worker_result", event.result)

    # Store questions in issue fields
    issue.fields["feedback_questions"] = questions

    # Check retry limit — if exhausted, don't spawn feedback agent
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
                message=f"Issue '{event.issue_id}' requested feedback but retries exhausted "
                f"({issue.failure_count}/{config.max_worker_retries})",
            )
        )
        return

    # Emit effect to spawn feedback agent
    effects.append(
        DispatchFeedbackAgentEffect(
            issue_id=event.issue_id,
            issue_type=issue.type,
            state=issue.state,
            questions=questions,
            issue=build_issue_context(state, event.issue_id),
        )
    )
```

- [ ] **Step 7: Implement `_handle_feedback_received` function**

Add after `_handle_needs_feedback`:

```python
def _handle_feedback_received(
    config: StateMachineConfig,
    state: State,
    event: FeedbackReceivedEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    """Handle feedback received from user: store context and re-dispatch worker."""
    if event.issue_id not in state.issues:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist")
        )
        return

    issue = state.issues[event.issue_id]

    # Feedback should only arrive when worker is not active
    if issue.worker_active:
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"Issue '{event.issue_id}' has worker_active=True — unexpected feedback",
            )
        )
        return

    state_def = config.get_state(issue.type, issue.state)
    if state_def.terminal:
        effects.append(
            ErrorEffect(
                issue_id=event.issue_id,
                message=f"Issue '{event.issue_id}' is in terminal state '{issue.state}'",
            )
        )
        return

    # Store feedback context
    issue.fields["feedback_context"] = event.feedback_context

    # Log feedback received
    append_log(issue, event.timestamp, "feedback_received", {"feedback_context": event.feedback_context})

    # Re-dispatch worker for current state
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
```

- [ ] **Step 8: Add routing in `reduce()` function**

In the `reduce()` function, add a new `elif` branch after the `WorkerFailedEvent` handler:

```python
    elif isinstance(event, FeedbackReceivedEvent):
        _handle_feedback_received(config, new_state, event, effects, ts)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_reducer_feedback.py -v`
Expected: All tests PASS

- [ ] **Step 10: Run full engine test suite**

Run: `uv run pytest tests/engine/ -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 11: Lint and type-check**

Run: `uv run ruff check src/orca/engine/reducer.py && uv run mypy src/orca/engine/reducer.py`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add src/orca/engine/reducer.py tests/engine/test_reducer_feedback.py tests/engine/conftest.py
git commit -m "feat(engine): handle needs_feedback outcome and FeedbackReceivedEvent in reducer"
```

---

### Task 4: Orchestrator — Route `DispatchFeedbackAgentEffect`

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py:417-428` (_route_effects)
- Modify: `src/orca/orchestrator/orchestrator.py:534-625` (result processing loop)
- Create: `src/orca/orchestrator/prompts/feedback-agent.md`

- [ ] **Step 1: Create feedback agent prompt template**

```markdown
<!-- src/orca/orchestrator/prompts/feedback-agent.md -->
# Feedback Agent

You are a user communication agent. A worker got stuck and needs clarification from a human user via Slack.

## Context

**Issue:** {{ issue.title | default("Untitled") }}

**State:** {{ state }}

**Worker's questions:**
{{ questions }}

{% if issue.feedback_context %}
**Previous feedback (from an earlier round):**
{{ issue.feedback_context }}
{% endif %}

{% if session_log_path %}
**Session log of the blocked worker:** `{{ session_log_path }}`
Read this file to understand what the worker was doing and why it got stuck. Reference specific details in your conversation with the user.
{% endif %}

## Instructions

1. Read the session log to understand the full context of what the worker was doing.
2. Use `slack_start_conversation` to open a DM with the user and explain the situation clearly. Include the worker's questions and relevant context from the session log.
3. Use `slack_wait_for_reply` to wait for the user's response.
4. If the user's answer is unclear or incomplete, ask follow-up questions using `slack_send_message` and `slack_wait_for_reply`. Continue until you have clear, actionable answers.
5. When you have sufficient answers, write the result file.

## Rules

- Be concise and specific in your Slack messages — the user is busy.
- Reference concrete details from the session log so the user knows exactly what you're asking about.
- Do not make assumptions about the user's intent — ask if unclear.
- The conversation is multi-turn. You decide when you have enough information.

## Output

Write the result JSON to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```

---

**IMPORTANT: Writing the result file is the final action of your session. The orchestrator will terminate this session shortly after detecting the result file. Complete ALL other work before writing the result file.**
```

- [ ] **Step 2: Update `_route_effects` to handle `DispatchFeedbackAgentEffect`**

In `src/orca/orchestrator/orchestrator.py`, update imports to include the new types:

```python
from orca.engine.types import (
    # ... existing imports ...
    DispatchFeedbackAgentEffect,
    FeedbackReceivedEvent,
)
```

Update `_route_effects` to accumulate feedback effects into `pending` alongside dispatch effects. Since the feedback agent is just another Claude Code worker, we can convert the effect into a `DispatchWorkerEffect`-like dispatch. But the orchestrator needs to know it's a feedback agent (different prompt, different result routing).

Add a new list to track pending feedback dispatches. In the `__init__`, no changes needed — we'll handle it inline.

Change `_route_effects`:

```python
    def _route_effects(self, effects: list[Effect], pending: list[DispatchWorkerEffect]) -> None:
        """Separate effects: dispatch workers immediately or log errors."""
        for effect in effects:
            if isinstance(effect, DispatchWorkerEffect):
                pending.append(effect)
            elif isinstance(effect, DispatchFeedbackAgentEffect):
                self._spawn_feedback_worker(effect)
            elif isinstance(effect, ErrorEffect):
                logger.error(
                    "ErrorEffect for issue %r: %s",
                    effect.issue_id,
                    effect.message,
                    extra={"event": "error_effect", "issue_id": effect.issue_id, "error": effect.message},
                )
```

- [ ] **Step 3: Implement `_spawn_feedback_worker`**

Add to the `Orchestrator` class:

```python
    def _spawn_feedback_worker(self, effect: DispatchFeedbackAgentEffect) -> None:
        """Spawn a feedback agent to collect user clarification via Slack."""
        if not self._slack_mcp_url:
            logger.warning(
                "Cannot spawn feedback agent for issue %s — Slack HITL not configured",
                effect.issue_id,
                extra={"event": "feedback_no_slack", "issue_id": effect.issue_id},
            )
            # Fire a WorkerFailedEvent since we can't collect feedback
            ts = self.now()
            event = WorkerFailedEvent(
                issue_id=effect.issue_id,
                error="needs_feedback requested but Slack HITL integration is not configured",
                timestamp=ts,
            )
            self.state, new_effects = reduce(self.config, self.state, event, self.generate_id, self.now)
            self.persistence.save(self.state)
            # Route any new effects (e.g., retry dispatch)
            pending: list[DispatchWorkerEffect] = []
            self._route_effects(new_effects, pending)
            for p in pending:
                self._spawn_worker(p)
            return

        worker_kind = "claude-code"
        worker = self.workers.get(worker_kind)
        if worker is None:
            logger.warning("No claude-code worker registered — cannot spawn feedback agent")
            return

        # Build feedback agent result format
        feedback_result_format: dict[str, Any] = {
            "outcome": {
                "type": "enum",
                "values": ["resolved", "unresolved"],
                "description": "",
                "values_description": {
                    "resolved": "Got answers from user",
                    "unresolved": "User unavailable or conversation inconclusive",
                },
            },
            "feedback_context": {
                "type": "string",
                "required_when": ["resolved"],
                "description": "Full Slack conversation text",
            },
            "reason": {
                "type": "string",
                "required_when": ["unresolved"],
                "description": "Why feedback could not be obtained",
            },
        }

        # Find the session log of the worker that requested feedback.
        # The session manifest (sessions.json) tracks all sessions; pick the
        # most recent completed session for this issue.
        session_log_path = ""
        if self._session_sync is not None:
            for entry in reversed(self._session_sync.manifest.entries):
                if (
                    entry.get("issue_id") == effect.issue_id
                    and entry.get("completed_at")
                    and entry.get("log_path")
                ):
                    session_log_path = str(entry["log_path"])
                    break

        # Record in-flight session for TUI
        tracking_id = str(uuid4())
        if self._session_sync is not None:
            workdir = self.repo_root or Path(".")
            self._session_sync.manifest.append(
                issue_id=effect.issue_id,
                state=f"{effect.state}:feedback",
                session_id=tracking_id,
                worktree_path=str(workdir),
                started_at=self.now(),
            )

        # Build a DispatchWorkerEffect-like wrapper for the feedback agent
        feedback_dispatch = DispatchWorkerEffect(
            issue_id=effect.issue_id,
            issue_type=effect.issue_type,
            state=effect.state,
            result_format=feedback_result_format,
            issue={
                **effect.issue,
                "feedback_questions": effect.questions,
                "session_log_path": session_log_path,
            },
        )

        prompt_template = "src/orca/orchestrator/prompts/feedback-agent.md"

        task: asyncio.Task[WorkerOutcome] = asyncio.create_task(
            self._run_worker_with_backoff(
                feedback_dispatch,
                worker,
                prompt_template,
                0.0,  # no backoff for feedback agent
                tracking_id,
            )
        )
        # Tag as feedback so result routing knows to fire FeedbackReceivedEvent
        self._in_flight[task] = (effect.issue_id, tracking_id)
        self._feedback_tasks.add(tracking_id)
        logger.info(
            "Feedback agent dispatched for issue %s",
            effect.issue_id,
            extra={"event": "feedback_agent_dispatched", "issue_id": effect.issue_id},
        )
```

- [ ] **Step 4: Add `_feedback_tasks` set and feedback result routing**

In `__init__`, add:

```python
self._feedback_tasks: set[str] = set()
```

In the result processing loop (after line ~548 where `isinstance(outcome, WorkerSuccess)` is checked), update the event construction to detect feedback tasks:

```python
                if isinstance(outcome, WorkerSuccess):
                    if tracking_id in self._feedback_tasks:
                        self._feedback_tasks.discard(tracking_id)
                        feedback_outcome = outcome.result.get("outcome")
                        if feedback_outcome == "resolved":
                            event = FeedbackReceivedEvent(
                                issue_id=issue_id,
                                feedback_context=str(outcome.result.get("feedback_context", "")),
                                timestamp=ts,
                            )
                        else:
                            event = WorkerFailedEvent(
                                issue_id=issue_id,
                                error=str(outcome.result.get("reason", "feedback unresolved")),
                                timestamp=ts,
                            )
                    else:
                        event = WorkerResultEvent(
                            issue_id=issue_id,
                            result=outcome.result,
                            timestamp=ts,
                        )
                else:
                    if tracking_id in self._feedback_tasks:
                        self._feedback_tasks.discard(tracking_id)
                    event = WorkerFailedEvent(
                        issue_id=issue_id,
                        error=outcome.error,
                        timestamp=ts,
                    )
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All 374+ tests PASS

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src/orca/orchestrator/orchestrator.py && uv run mypy src/orca/orchestrator/orchestrator.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py src/orca/orchestrator/prompts/feedback-agent.md
git commit -m "feat(orchestrator): spawn feedback agent on DispatchFeedbackAgentEffect, route results"
```

---

### Task 5: Integration Test — Full Feedback Round-Trip

**Files:**
- Test: `tests/engine/test_reducer_feedback.py` (append)

- [ ] **Step 1: Write a full round-trip test**

Append to `tests/engine/test_reducer_feedback.py`:

```python
class TestFeedbackRoundTrip:
    """End-to-end: worker -> needs_feedback -> feedback_received -> re-dispatch -> complete."""

    def test_full_feedback_then_complete(self, feedback_config_yaml: str) -> None:
        config = parse_config(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # 1. Create issue — worker dispatched in implementing
        state, effects = reduce(
            config, state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen, _clock(),
        )
        assert state.issues["A"].state == "implementing"
        assert state.issues["A"].worker_active is True

        # 2. Worker returns needs_feedback
        state, effects = reduce(
            config, state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "REST or gRPC?"},
                timestamp="t1",
            ),
            gen, _clock(),
        )
        assert state.issues["A"].worker_active is False
        assert state.issues["A"].failure_count == 1
        assert state.issues["A"].fields["feedback_questions"] == "REST or gRPC?"
        feedback_effects = [e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]
        assert len(feedback_effects) == 1

        # 3. Feedback agent completes — user said REST
        state, effects = reduce(
            config, state,
            FeedbackReceivedEvent(
                issue_id="A",
                feedback_context="User: Use REST API for all new endpoints.",
                timestamp="t2",
            ),
            gen, _clock(),
        )
        assert state.issues["A"].worker_active is True
        assert state.issues["A"].fields["feedback_context"] == "User: Use REST API for all new endpoints."
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1

        # 4. Re-dispatched worker completes successfully
        state, effects = reduce(
            config, state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "complete"},
                timestamp="t3",
            ),
            gen, _clock(),
        )
        assert state.issues["A"].state == "done"
        assert state.issues["A"].worker_active is False
        assert state.issues["A"].failure_count == 0  # reset on success

    def test_multiple_feedback_rounds(self, feedback_config_yaml: str) -> None:
        """Worker can request feedback multiple times (within retry budget)."""
        config = parse_config(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create
        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen, _clock(),
        )

        # Round 1: needs_feedback
        state, effects = reduce(
            config, state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q1?"},
                timestamp="t1",
            ),
            gen, _clock(),
        )
        assert state.issues["A"].failure_count == 1
        assert len([e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]) == 1

        # Round 1: feedback received
        state, _ = reduce(
            config, state,
            FeedbackReceivedEvent(issue_id="A", feedback_context="A1", timestamp="t2"),
            gen, _clock(),
        )

        # Round 2: needs_feedback again
        state, effects = reduce(
            config, state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q2?"},
                timestamp="t3",
            ),
            gen, _clock(),
        )
        assert state.issues["A"].failure_count == 2
        assert state.issues["A"].fields["feedback_questions"] == "Q2?"
        assert len([e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]) == 1

        # Round 2: feedback received
        state, _ = reduce(
            config, state,
            FeedbackReceivedEvent(issue_id="A", feedback_context="A2", timestamp="t4"),
            gen, _clock(),
        )

        # Round 3: needs_feedback — but this will exhaust retries (max=3)
        state, effects = reduce(
            config, state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q3?"},
                timestamp="t5",
            ),
            gen, _clock(),
        )
        assert state.issues["A"].failure_count == 3
        # Should NOT dispatch feedback agent — retries exhausted
        assert len([e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]) == 0
        assert len([e for e in effects if isinstance(e, ErrorEffect)]) == 1
```

- [ ] **Step 2: Run the integration tests**

Run: `uv run pytest tests/engine/test_reducer_feedback.py::TestFeedbackRoundTrip -v`
Expected: All PASS

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -x -q`
Expected: All tests PASS

- [ ] **Step 4: Full lint and type-check**

Run: `uv run ruff check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/engine/test_reducer_feedback.py
git commit -m "test(engine): add feedback round-trip integration tests"
```
