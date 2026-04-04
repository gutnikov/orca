# Remove HITL from Engine — Design Spec

**Date:** 2026-04-04
**Status:** Draft

## Summary

Remove `needs_feedback` reserved outcome and all HITL (human-in-the-loop) machinery from orca's engine and orchestrator. HITL becomes a prompt-level concern: workers that need human input use communication tools (Slack, email, etc.) directly and orca never knows the difference.

The `slack-hitl` MCP server is removed from the repo entirely — it's a standalone tool, not an orca concern.

## Motivation

The engine currently treats HITL as a first-class concept with a reserved outcome, dedicated effect/event types, feedback-agent orchestration, and shared retry budgets. This adds significant complexity (~600+ lines across engine, orchestrator, and tests) for something that can be handled entirely by the worker agent:

1. A worker that needs user input can call Slack (or any communication) MCP tools directly.
2. A worker that might wait on a human just gets a longer timeout.
3. A worker that fails (whether due to missing feedback or anything else) gets retried by existing retry logic.

Orca doesn't need to know *why* a worker is taking long or *how* it communicates with users.

## Design

### Engine: types.py

Delete:
- `DispatchFeedbackAgentEffect` dataclass
- `FeedbackReceivedEvent` dataclass
- Remove both from the `Effect` and `Event` union types

### Engine: reducer.py

Delete:
- `_handle_needs_feedback()` function
- `_handle_feedback_received()` function
- The `if outcome == "needs_feedback"` early-return branch in `_handle_worker_result()`
- The `FeedbackReceivedEvent` case in the main `reduce()` dispatch
- The cleanup of `feedback_questions` / `feedback_context` fields on state transition

### Engine: config.py

Delete:
- `_RESERVED_OUTCOMES` constant
- The validation exemption that allows `needs_feedback` to skip `on:` rule requirements

After this change, if someone puts `needs_feedback` in their outcome enum values, it requires an `on:` rule like any other outcome.

### Orchestrator: orchestrator.py

Delete:
- `_feedback_tasks: set[str]` instance variable
- `_spawn_feedback_worker()` method
- The `isinstance(effect, DispatchFeedbackAgentEffect)` branch in effect dispatch
- The `if tracking_id in self._feedback_tasks` detection in the worker completion handler

### Orchestrator: prompts/feedback-agent.md

Delete the entire file.

### Orchestrator: integrations.slack config

Remove parsing/validation of `integrations.slack` configuration (bot_token, app_token, env var lookups).

### slack-hitl MCP server

Delete `src/orca/mcp_servers/slack_hitl/` entirely. This is a standalone MCP server with no orca imports — it can live in its own repo if needed.

### Tests

Delete:
- `tests/engine/test_types_feedback.py`
- `tests/engine/test_reducer_feedback.py`
- The `feedback_config_yaml` fixture from `tests/engine/conftest.py`

### Docs

Delete:
- `docs/superpowers/specs/2026-03-26-slack-hitl-design.md`
- `docs/superpowers/specs/2026-03-31-needs-feedback-design.md`

### Examples: orca.yml

In `examples/project/orca.yml`:
- Remove `needs_feedback` from the `implementing` state's outcome values
- Remove the `feedback_questions` field from result_format
- Remove any `integrations.slack` config block

### Examples: worker-driven HITL

Update `examples/project/prompts/implementing.md` to show the worker-driven HITL pattern: instruct the worker in its prompt to use Slack tools when blocked, ask its question, wait for a reply, and continue. Set a longer timeout on the state to accommodate human response time.

### README.md

Replace the `needs_feedback` / HITL section with a "Worker-driven HITL" section:
- Pattern: give the worker communication MCP tools, instruct it in the prompt to ask when blocked, set a longer timeout
- Minimal workflow YAML snippet showing a state with a longer timeout
- Minimal prompt snippet showing "if blocked, use slack tools to ask"
- Key message: HITL is a prompt concern, not an engine concern

## What does NOT change

- The `slack-hitl` MCP server functionality — it just moves out of this repo
- Workers can still ask users questions — they just do it directly
- Retry logic — `max_worker_retries` still works, just no longer shared with feedback rounds
- Worker timeouts — already supported, just use longer values for HITL-capable states
- Everything else in the engine/orchestrator

## Migration

Users currently relying on `needs_feedback`:
1. Remove `needs_feedback` from outcome enum values
2. Add Slack (or other) MCP tools to the worker's environment
3. Add instructions to the worker prompt to use those tools when blocked
4. Increase timeout on states where human interaction is expected
5. Configure the `slack-hitl` MCP server independently (not via orca's `integrations.slack`)
