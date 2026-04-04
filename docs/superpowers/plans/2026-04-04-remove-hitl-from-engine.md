# Remove HITL from Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all `needs_feedback` / HITL machinery from the orca engine and orchestrator, delete the `slack-hitl` MCP server, and replace docs/examples with the worker-driven HITL pattern.

**Architecture:** Pure deletion across engine types, reducer, config validation, and orchestrator. The `slack-hitl` MCP server directory is removed entirely. Examples and README are updated to show the worker-driven pattern (workers use Slack tools directly via longer timeouts).

**Tech Stack:** Python 3.12, pytest, ruff, mypy

---

### Task 1: Remove feedback types from engine

**Files:**
- Modify: `src/orca/engine/types.py:213-251`

- [ ] **Step 1: Delete `FeedbackReceivedEvent` dataclass**

Remove lines 213-217:

```python
@dataclass(frozen=True)
class FeedbackReceivedEvent:
    issue_id: str
    feedback_context: str
    timestamp: str
```

- [ ] **Step 2: Remove `FeedbackReceivedEvent` from `Event` union**

Change line 220:

```python
Event = CreateEvent | AdvanceEvent | WorkerResultEvent | WorkerFailedEvent | FeedbackReceivedEvent
```

to:

```python
Event = CreateEvent | AdvanceEvent | WorkerResultEvent | WorkerFailedEvent
```

- [ ] **Step 3: Delete `DispatchFeedbackAgentEffect` dataclass**

Remove lines 242-248:

```python
@dataclass(frozen=True)
class DispatchFeedbackAgentEffect:
    issue_id: str
    issue_type: str
    state: str
    questions: str
    issue: dict[str, Any]
```

- [ ] **Step 4: Remove `DispatchFeedbackAgentEffect` from `Effect` union**

Change line 251:

```python
Effect = DispatchWorkerEffect | ErrorEffect | DispatchFeedbackAgentEffect
```

to:

```python
Effect = DispatchWorkerEffect | ErrorEffect
```

- [ ] **Step 5: Run type checker to verify**

Run: `uv run mypy src/orca/engine/types.py`
Expected: PASS (types file is self-contained after these removals)

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/types.py
git commit -m "refactor(engine): remove FeedbackReceivedEvent and DispatchFeedbackAgentEffect types"
```

---

### Task 2: Remove feedback logic from reducer

**Files:**
- Modify: `src/orca/engine/reducer.py:1-540`

- [ ] **Step 1: Remove feedback imports**

In the import block (lines 16-32), remove `DispatchFeedbackAgentEffect` and `FeedbackReceivedEvent` from the imports:

```python
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
)
```

- [ ] **Step 2: Remove `FeedbackReceivedEvent` dispatch from `reduce()`**

Remove lines 55-56 from the `reduce()` function:

```python
    elif isinstance(event, FeedbackReceivedEvent):
        _handle_feedback_received(config, new_state, event, effects, ts)
```

- [ ] **Step 3: Remove `needs_feedback` branch from `_handle_worker_result()`**

Remove lines 224-227 (the early return for needs_feedback):

```python
    # Reserved outcome: needs_feedback — handled before on: rule lookup
    if outcome == "needs_feedback":
        _handle_needs_feedback(config, state, event, issue, effects, ts)
        return
```

- [ ] **Step 4: Delete `_handle_needs_feedback()` function**

Delete the entire function (lines 351-398):

```python
def _handle_needs_feedback(
    config: StateMachineConfig,
    state: State,
    event: WorkerResultEvent,
    issue: Issue,
    effects: list[Effect],
    ts: str,
) -> None:
    ...
```

- [ ] **Step 5: Delete `_handle_feedback_received()` function**

Delete the entire function (lines 401-450):

```python
def _handle_feedback_received(
    config: StateMachineConfig,
    state: State,
    event: FeedbackReceivedEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    ...
```

- [ ] **Step 6: Remove feedback field cleanup from `_apply_transition()`**

Remove lines 538-540 from `_apply_transition()`:

```python
    # Clear transient feedback fields — they belong to the previous state's feedback loop
    issue.fields.pop("feedback_context", None)
    issue.fields.pop("feedback_questions", None)
```

- [ ] **Step 7: Run type checker**

Run: `uv run mypy src/orca/engine/reducer.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/orca/engine/reducer.py
git commit -m "refactor(engine): remove needs_feedback and feedback_received logic from reducer"
```

---

### Task 3: Remove reserved outcomes from config validation

**Files:**
- Modify: `src/orca/engine/config.py:24,234-247`

- [ ] **Step 1: Delete `_RESERVED_OUTCOMES` constant**

Remove line 24:

```python
_RESERVED_OUTCOMES = frozenset({"needs_feedback"})
```

- [ ] **Step 2: Simplify Rule 10 validation**

Replace the Rule 10 block (lines 234-247) which exempts reserved outcomes:

```python
            # Rule 10: if a state has a worker with an outcome enum, at least one non-reserved
            # outcome value must have a matching on: rule (reserved outcomes like needs_feedback
            # do not need on: rules, but the state must still be able to progress)
            if state.worker is not None:
                outcome_field = state.worker.result_format.get("outcome")
                if isinstance(outcome_field, EnumFieldDef):
                    non_reserved = [v for v in outcome_field.values if v not in _RESERVED_OUTCOMES]
                    routable = [v for v in non_reserved if v in state.on]
                    if not routable:
                        msg = (
                            f"Type '{type_name}', state '{name}' has no non-reserved outcome values "
                            f"with matching on: rules — state cannot progress"
                        )
                        raise ConfigValidationError(msg)
```

with a simpler version that no longer exempts reserved outcomes:

```python
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
```

- [ ] **Step 3: Run type checker**

Run: `uv run mypy src/orca/engine/config.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/orca/engine/config.py
git commit -m "refactor(engine): remove _RESERVED_OUTCOMES and simplify config validation"
```

---

### Task 4: Delete feedback tests and fixtures

**Files:**
- Delete: `tests/engine/test_types_feedback.py`
- Delete: `tests/engine/test_reducer_feedback.py`
- Modify: `tests/engine/conftest.py:177-208`
- Modify: `tests/engine/test_config.py:708-774`

- [ ] **Step 1: Delete test_types_feedback.py**

```bash
rm tests/engine/test_types_feedback.py
```

- [ ] **Step 2: Delete test_reducer_feedback.py**

```bash
rm tests/engine/test_reducer_feedback.py
```

- [ ] **Step 3: Remove `feedback_config_yaml` fixture from conftest.py**

Delete the fixture at lines 177-208 in `tests/engine/conftest.py`:

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

initial: implementing

max-retries: 3
"""
```

- [ ] **Step 4: Update `TestNeedsFeedbackValidation` in test_config.py**

Delete the entire `TestNeedsFeedbackValidation` class (lines 708-774) in `tests/engine/test_config.py`. Both tests are no longer relevant:
- `test_needs_feedback_outcome_without_on_rule_is_valid` — reserved outcome exemption is removed
- `test_needs_feedback_only_outcome_is_invalid` — same exemption logic

- [ ] **Step 5: Run all engine tests**

Run: `uv run pytest tests/engine/ -v`
Expected: All tests PASS (no references to deleted types/functions remain)

- [ ] **Step 6: Commit**

```bash
git add -u tests/engine/
git commit -m "test(engine): remove feedback tests, fixtures, and config validation tests"
```

---

### Task 5: Remove feedback machinery from orchestrator

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py`
- Delete: `src/orca/orchestrator/prompts/feedback-agent.md`

- [ ] **Step 1: Remove feedback imports**

In the import block (lines 15-25), remove `DispatchFeedbackAgentEffect` and `FeedbackReceivedEvent`:

```python
from orca.engine.types import (
    DispatchWorkerEffect,
    Effect,
    ErrorEffect,
    State,
    StateMachineConfig,
    WorkerFailedEvent,
    WorkerResultEvent,
)
```

- [ ] **Step 2: Remove `_feedback_tasks` from `__init__`**

Delete line 89:

```python
        self._feedback_tasks: set[str] = set()
```

- [ ] **Step 3: Delete `_spawn_feedback_worker()` method**

Delete the entire method (lines 318-401):

```python
    def _spawn_feedback_worker(self, effect: DispatchFeedbackAgentEffect) -> None:
        ...
```

- [ ] **Step 4: Remove `DispatchFeedbackAgentEffect` branch from `_route_effects()`**

In `_route_effects()` (line 588-589), remove:

```python
            elif isinstance(effect, DispatchFeedbackAgentEffect):
                self._spawn_feedback_worker(effect)
```

- [ ] **Step 5: Remove feedback task handling from completion handler**

In the `run()` method's completion handler (lines 724-755), simplify the `WorkerSuccess` branch. Replace:

```python
                if isinstance(outcome, WorkerSuccess):
                    if tracking_id in self._feedback_tasks:
                        self._feedback_tasks.discard(tracking_id)
                        feedback_outcome = outcome.result.get("outcome")
                        if feedback_outcome == "resolved":
                            event: WorkerResultEvent | WorkerFailedEvent | FeedbackReceivedEvent = (
                                FeedbackReceivedEvent(
                                    issue_id=issue_id,
                                    feedback_context=str(outcome.result.get("feedback_context", "")),
                                    timestamp=ts,
                                )
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

with:

```python
                if isinstance(outcome, WorkerSuccess):
                    event: WorkerResultEvent | WorkerFailedEvent = WorkerResultEvent(
                        issue_id=issue_id,
                        result=outcome.result,
                        timestamp=ts,
                    )
                else:
                    event = WorkerFailedEvent(
                        issue_id=issue_id,
                        error=outcome.error,
                        timestamp=ts,
                    )
```

- [ ] **Step 6: Delete feedback-agent.md prompt**

```bash
rm src/orca/orchestrator/prompts/feedback-agent.md
```

- [ ] **Step 7: Run type checker**

Run: `uv run mypy src/orca/orchestrator/orchestrator.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add -u src/orca/orchestrator/
git commit -m "refactor(orchestrator): remove feedback agent spawning and HITL routing"
```

---

### Task 6: Remove integrations config and slack-hitl MCP server

**Files:**
- Modify: `src/orca/orchestrator/config_types.py`
- Delete: `src/orca/mcp_servers/slack_hitl/` (entire directory)
- Delete: `tests/mcp_servers/test_slack_client.py`
- Delete: `tests/mcp_servers/test_server.py`
- Delete: `tests/mcp_servers/test_integration.py`
- Delete: `tests/mcp_servers/__init__.py`
- Modify: `tests/orchestrator/test_config_types.py`

- [ ] **Step 1: Remove integrations from config_types.py**

In `src/orca/orchestrator/config_types.py`, remove:

1. The `os` import (line 2)
2. `SlackConfig` dataclass (lines 8-10)
3. `IntegrationsConfig` dataclass (lines 13-16)
4. `_resolve_token()` function (lines 19-32)
5. `parse_integrations()` function (lines 48-60)

The file should only contain `OrchestratorConfig` and `parse_orchestrator_config`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OrchestratorConfig:
    base_branch: str = "origin/main"


def parse_orchestrator_config(raw: dict[str, Any] | None) -> OrchestratorConfig:
    """Parse orchestrator-level config from orca.yml (fields outside the engine config)."""
    if not raw:
        return OrchestratorConfig()
    base_branch = raw.get("base_branch", "origin/main")
    return OrchestratorConfig(base_branch=str(base_branch))
```

- [ ] **Step 2: Delete slack-hitl MCP server directory**

```bash
rm -rf src/orca/mcp_servers/slack_hitl/
```

Check if `src/orca/mcp_servers/` is now empty (aside from `__init__.py` or `__pycache__`). If so, delete the whole directory:

```bash
ls src/orca/mcp_servers/
```

- [ ] **Step 3: Delete mcp_servers tests**

```bash
rm -rf tests/mcp_servers/
```

- [ ] **Step 4: Remove `TestParseIntegrations` from test_config_types.py**

In `tests/orchestrator/test_config_types.py`, remove the `parse_integrations` import and the entire `TestParseIntegrations` class (lines 8-35). Update the import:

```python
from orca.orchestrator.config_types import parse_orchestrator_config
```

The file should only contain `TestParseOrchestratorConfig`.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Run full lint and type check**

Run: `uv run ruff check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -u src/orca/mcp_servers/ src/orca/orchestrator/config_types.py tests/mcp_servers/ tests/orchestrator/test_config_types.py
git commit -m "refactor: remove slack-hitl MCP server and integrations config"
```

---

### Task 7: Update examples with worker-driven HITL pattern

**Files:**
- Modify: `examples/project/orca.yml`
- Modify: `examples/project/prompts/implementing.md`

- [ ] **Step 1: Remove needs_feedback from orca.yml implementing state**

In `examples/project/orca.yml`, replace the `implementing` state block (lines 85-111) with:

```yaml
  # Stage 3: Implement the feature following the plan, making all tests pass.
  # If the worker needs user clarification, it uses Slack tools directly.
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      timeout: 3600                    # 60 minutes — allows time for human interaction
      result_format:
        outcome:
          type: enum
          values: [done, blocked]
          description: "Whether implementation is complete"
          values_description:
            done: "All tests pass, pre-commit hooks pass, changes committed"
            blocked: "Cannot proceed — plan is insufficient or issue is unclear"
        summary:
          type: string
          description: "Brief summary of what was implemented or what is blocking"
    on:
      done: applying
      blocked: planning                # loop back to revise the plan
```

- [ ] **Step 2: Add worker-driven HITL instructions to implementing prompt**

In `examples/project/prompts/implementing.md`, add a new section after "### If Blocked":

```markdown
### If You Need User Clarification

If you are blocked on a question that only the user can answer:

1. Use the `slack_start_conversation` tool to open a DM with the user
2. Explain the situation clearly, referencing specific code or decisions
3. Use `slack_wait_for_reply` to wait for their response
4. If the answer is unclear, ask follow-up questions
5. Once you have a clear answer, continue implementing

Do NOT report `blocked` for questions the user can answer — ask them directly.
```

- [ ] **Step 3: Commit**

```bash
git add examples/project/orca.yml examples/project/prompts/implementing.md
git commit -m "docs(examples): replace needs_feedback with worker-driven HITL pattern"
```

---

### Task 8: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace needs_feedback section in Workflow Features**

Replace the "User feedback via Slack" block (lines 184-209) with:

```markdown
**Worker-driven HITL** — any worker can talk to users directly using communication MCP tools (Slack, email, etc.). Instruct the worker in its prompt to ask when blocked, and set a longer timeout to accommodate human response time:

```yaml
states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implement.md
      timeout: 3600                  # 60 min — allows human interaction
      result_format:
        outcome:
          type: enum
          values: [done, blocked]
    on:
      done: applying
      blocked: planning
```

In the worker prompt:
```
If you need clarification from the user, use the slack_start_conversation
and slack_wait_for_reply tools to ask them directly. Do not report blocked
for questions the user can answer.
```

Workers discover MCP tools from the project's `.mcp.json` — orca doesn't need to know which communication channel is used.
```

- [ ] **Step 2: Replace the Integrations Slack section**

Replace the "Integrations" Slack block (lines 285-300) with:

```markdown
## Integrations

**Slack** — Workers can conduct multi-turn Slack DM conversations during execution using the `slack-hitl` MCP server. Configure it in your project's `.mcp.json` and instruct workers in their prompts to use the tools when they need human input. See the [slack-hitl MCP server](https://github.com/anthropics/slack-hitl-mcp) for setup instructions.
```

(Note: the GitHub URL is a placeholder — adjust to wherever the MCP server is published.)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: replace HITL documentation with worker-driven pattern"
```

---

### Task 9: Delete obsolete design specs

**Files:**
- Delete: `docs/superpowers/specs/2026-03-26-slack-hitl-design.md`
- Delete: `docs/superpowers/specs/2026-03-31-needs-feedback-design.md`

- [ ] **Step 1: Delete obsolete specs**

```bash
rm docs/superpowers/specs/2026-03-26-slack-hitl-design.md
rm docs/superpowers/specs/2026-03-31-needs-feedback-design.md
```

- [ ] **Step 2: Commit**

```bash
git add -u docs/superpowers/specs/
git commit -m "docs: remove obsolete HITL and needs_feedback design specs"
```

---

### Task 10: Final verification

- [ ] **Step 1: Run full lint**

Run: `uv run ruff check .`
Expected: PASS

- [ ] **Step 2: Run format check**

Run: `uv run ruff format --check .`
Expected: PASS

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/`
Expected: PASS

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Grep for any remaining feedback/HITL references in source**

Run: `rg "needs_feedback|DispatchFeedbackAgentEffect|FeedbackReceivedEvent|_handle_needs_feedback|_handle_feedback_received|_feedback_tasks|_spawn_feedback_worker|feedback_questions|feedback_context|_RESERVED_OUTCOMES" src/`
Expected: No matches

- [ ] **Step 6: Verify no broken imports**

Run: `python -c "from orca.engine.types import Effect, Event; from orca.engine.reducer import reduce; from orca.orchestrator.orchestrator import Orchestrator"`
Expected: No import errors
