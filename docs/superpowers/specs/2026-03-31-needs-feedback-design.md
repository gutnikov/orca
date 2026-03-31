# Needs Feedback: User Clarification via Slack

## Overview

Any worker can signal that it's blocked and needs user clarification by returning `needs_feedback` as its outcome. The engine treats this as a reserved outcome — no `on:` rule required. A real Claude Code feedback agent is spawned to conduct a multi-turn Slack conversation with the user, then the original worker is re-dispatched with the conversation context.

## Design Principles

- **Engine-level concern** — feedback is a first-class concept in the reducer, not an orchestrator hack. Full audit trail in event_log.
- **Opt-in per state** — only states that include `needs_feedback` in their `result_format.outcome.values` expose it to workers. No global magic.
- **Real agent** — the feedback agent is a full Claude Code CLI worker with session log access and Slack HITL tools. It drives a multi-turn conversation and decides when to wrap up.
- **Retry budget** — each feedback round increments `failure_count`, sharing the limit with actual failures via `max_worker_retries`.

## Engine Changes

### Reserved Outcome

`needs_feedback` is a reserved string. The config validator (`config.py`) allows it in a state's `outcome.values` without requiring a matching key in `on:`. The reducer recognizes it before looking up `on:` rules.

### New Types (`types.py`)

**`DispatchFeedbackAgentEffect`** — emitted by the reducer when a worker returns `needs_feedback`:
```python
@dataclass(frozen=True)
class DispatchFeedbackAgentEffect:
    issue_id: str
    issue_type: str
    state: str
    questions: str              # free-form text from worker
    issue: dict[str, Any]       # full issue context for prompt rendering
```

Note: `session_log_path` is not in the effect — the reducer is pure and doesn't know about log files. The orchestrator attaches the log path when spawning the feedback worker (it already tracks log paths in `_session_log_paths`).

**`FeedbackReceivedEvent`** — fired by the orchestrator when the feedback agent completes successfully:
```python
@dataclass(frozen=True)
class FeedbackReceivedEvent:
    issue_id: str
    feedback_context: str       # full Slack conversation text
    timestamp: datetime
```

### Reducer Logic (`reducer.py`)

**`_handle_worker_result()`** — after extracting `outcome`, before looking up `state_def.on`:

```python
if outcome == "needs_feedback":
    questions = event.result.get("feedback_questions", "")
    # 1. Set worker_active = False
    # 2. Increment failure_count
    # 3. Log worker_result event (outcome: needs_feedback)
    # 4. Store questions in issue.fields["feedback_questions"]
    # 5. If failure_count > max_worker_retries: stop (treat as exhausted)
    # 6. Emit DispatchFeedbackAgentEffect
    # Return early
```

**New `_handle_feedback_received()`**:

```python
def _handle_feedback_received(config, state, event, generate_id, now):
    # 1. Validate: issue exists, not terminal, worker_active == False
    # 2. Store event.feedback_context in issue.fields["feedback_context"]
    # 3. Log feedback_received event in event_log
    # 4. Set worker_active = True
    # 5. Emit DispatchWorkerEffect for current state (re-dispatch)
```

**`reduce()`** — add routing:

```python
case FeedbackReceivedEvent():
    return _handle_feedback_received(config, state, event, generate_id, now)
```

### Config Validation (`config.py`)

Where the validator checks that all `outcome.values` have matching `on:` keys (~line 228), skip `needs_feedback`. Where it checks that all `on:` keys are in `outcome.values`, no change needed (authors don't declare `on: needs_feedback`).

## Orchestrator Changes

### Effect Handling (`orchestrator.py`)

In the effect processing loop, handle the new effect:

```python
case DispatchFeedbackAgentEffect():
    asyncio.create_task(self._spawn_feedback_worker(effect))
```

### Feedback Worker (`_spawn_feedback_worker`)

Spawns a Claude Code CLI agent using the existing `CliAgentWorker` infrastructure:

- **Prompt template:** Built-in `prompts/feedback-agent.md` (ships with orca, not user-provided)
- **Template context:** The effect carries `questions` and `issue` (full issue fields including any prior `feedback_context`). The orchestrator adds the `session_log_path` from `_session_log_paths` when rendering the prompt.
- **MCP access:** Gets `SLACK_HITL_MCP_URL` env var, same as any other worker
- **Result format:**
  ```yaml
  outcome:
    type: enum
    values: [resolved, unresolved]
    values_description:
      resolved: "Got answers from user"
      unresolved: "User unavailable or conversation inconclusive"
  feedback_context:
    type: string
    required_when: [resolved]
    description: "Full Slack conversation text"
  reason:
    type: string
    required_when: [unresolved]
    description: "Why feedback could not be obtained"
  ```

### Result Routing

On feedback worker completion:
- **`resolved`** → fire `FeedbackReceivedEvent(issue_id, feedback_context, timestamp)` into the reducer
- **`unresolved`** → fire `WorkerFailedEvent(issue_id, error=reason, timestamp)` — burns a retry

### Session Log Path

The orchestrator already tracks session log paths in `_session_log_paths`. When handling a `DispatchFeedbackAgentEffect`, it looks up the most recent session log for the issue and passes the path to the feedback agent's prompt template. The feedback agent can read the log for full context on what the worker was doing and why it got stuck.

## Worker Interface

### Triggering Feedback

A worker returns `needs_feedback` only if its state's result format includes it:

```yaml
# orca.yml
states:
  build_and_run:
    worker:
      kind: claude-code
      prompt: prompts/build-and-run.md
      result_format:
        outcome:
          type: enum
          values: [done, fail, needs_feedback]
          values_description:
            done: "App built, container running and healthy"
            fail: "Could not build or run"
            needs_feedback: "Blocked — need clarification from user"
        feedback_questions:
          type: string
          required_when: [needs_feedback]
          description: "Questions for the user"
        reason:
          type: string
          required_when: [fail]
```

The worker writes:
```json
{
  "outcome": "needs_feedback",
  "feedback_questions": "The uploadLogo RPC changed from streaming to unary. Should I rewrite the hook to use the new unary API, or is there a compatibility shim?"
}
```

### Receiving Answers

When re-dispatched, the worker's prompt template has access to:
- `{{ issue.feedback_context }}` — full Slack conversation text
- `{{ issue.feedback_questions }}` — what it originally asked

Prompt template authors can optionally add:
```jinja2
{% if issue.feedback_context %}
## User Feedback
{{ issue.feedback_context }}
{% endif %}
```

## TUI Integration

The feedback agent appears as a normal worker session in the TUI — visible in the workers list and phases panel. Its session log shows the Slack conversation activity.

## Retry & Failure Semantics

- Each `needs_feedback` round increments `failure_count` (shares budget with `max_worker_retries`)
- If `failure_count >= max_worker_retries` when `needs_feedback` is returned, the issue stops — no feedback agent is spawned
- An `unresolved` feedback result also increments `failure_count` (via `WorkerFailedEvent`)
- Example with `max_worker_retries: 3`: a worker could fail once, request feedback once, get re-dispatched, and still have one retry left

## Workflow YAML — No Changes Required

No new top-level config keys. Authors enable feedback per-state by adding `needs_feedback` to the outcome enum. The Slack HITL integration must be configured in `integrations.slack` (existing config).

## Files Changed

| File | Change |
|------|--------|
| `src/orca/engine/types.py` | Add `DispatchFeedbackAgentEffect`, `FeedbackReceivedEvent` |
| `src/orca/engine/reducer.py` | Handle `needs_feedback` in `_handle_worker_result`, add `_handle_feedback_received` |
| `src/orca/engine/config.py` | Allow `needs_feedback` in outcome values without `on:` rule |
| `src/orca/orchestrator/orchestrator.py` | Handle `DispatchFeedbackAgentEffect`, implement `_spawn_feedback_worker`, route feedback results |
| `src/orca/orchestrator/prompts/feedback-agent.md` | Built-in prompt template for the feedback agent (new file) |
