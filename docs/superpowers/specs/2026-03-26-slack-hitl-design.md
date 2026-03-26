# Slack Human-in-the-Loop (HITL) MCP Server

## Overview

An MCP server that gives Claude Code workers the ability to conduct multi-turn Slack DM conversations with humans. No new worker types are introduced — a HITL step is a regular `claude-code` worker whose prompt instructs it to use Slack tools instead of coding tools. The agent drives the conversation, decides when it has enough information, and writes `result.json` to advance the state machine.

## Architecture

### MCP Server: `slack-hitl`

A shared, long-lived MCP server process started by the orchestrator at startup (when `integrations.slack` is present in `orca.yml`). All Claude Code workers connect to it via SSE transport. The server maintains a single Slack Socket Mode connection and multiplexes conversations across workers.

**Process model:**
- The orchestrator starts the MCP server as a subprocess on startup and shuts it down on exit.
- The server connects to Slack via `slack_sdk.socket_mode.aio.AsyncSocketModeClient`.
- It exposes an SSE endpoint that Claude Code workers connect to via `--mcp-server-url` or equivalent config.
- The server routes incoming Slack messages to the correct waiting tool call using a `dict[tuple[channel_id, thread_ts], asyncio.Future]` map.

**File structure:**
```
src/orca/mcp_servers/slack_hitl/
    __init__.py
    server.py       # MCP server entry point, tool definitions, SSE transport
    slack_client.py # Slack Socket Mode wrapper, message routing
```

**Dependencies:**
- `slack_sdk` — Slack Socket Mode async client
- `mcp` — MCP Python SDK for building servers

### Tools

#### `slack_start_conversation`

Opens a DM with a Slack user and posts the initial message. The returned `thread_ts` becomes the session identifier for all subsequent interactions.

- **Params:** `user_id: str`, `text: str`
- **Returns:** `{ "channel": "D...", "thread_ts": "..." }`
- **Behavior:** Calls `conversations.open` to get/create the DM channel, then posts the message. The `thread_ts` of the posted message is the thread root.

#### `slack_send_message`

Posts a follow-up message in an existing conversation thread.

- **Params:** `channel: str`, `thread_ts: str`, `text: str`
- **Returns:** `{ "ts": "..." }`

#### `slack_wait_for_reply`

Blocks until the human posts a message in the specified thread, or times out.

- **Params:** `channel: str`, `thread_ts: str`, `timeout_seconds: int` (default: 3600)
- **Returns:** `{ "text": "...", "user": "...", "ts": "..." }`
- **Timeout:** Returns an error if no message arrives within `timeout_seconds`.
- **Queuing:** If the user sends multiple messages before the agent calls wait, the first unread message is returned immediately. Subsequent messages queue and are returned by subsequent wait calls.

### Conversation Threading

Each HITL session creates its own thread in the user's DM channel:

1. `slack_start_conversation` posts a root message → gets `thread_ts`
2. All follow-ups from the agent use `slack_send_message` with that `thread_ts`
3. All waits use `slack_wait_for_reply` with that `thread_ts`
4. The MCP server only routes messages matching `(channel, thread_ts)` to the corresponding future

This means multiple HITL workers can DM the same user concurrently — each thread is independent.

## Configuration

### `orca.yml`

Slack credentials live under `integrations.slack`:

```yaml
integrations:
  slack:
    bot_token: "xoxb-..."
    app_token: "xapp-..."
```

Or reference environment variables to avoid secrets in the file:

```yaml
integrations:
  slack:
    bot_token_env: "SLACK_BOT_TOKEN"
    app_token_env: "SLACK_APP_TOKEN"
```

The orchestrator reads these at startup and passes them as environment variables to the MCP server process.

### Slack App Requirements

The Slack app needs:
- **Socket Mode** enabled (for real-time events without a public endpoint)
- **Bot token scopes:** `chat:write`, `im:write`, `im:read`, `im:history`
- **Event subscriptions:** `message.im` (to receive DM replies)

### Workflow State Definition

A HITL state looks like any other state in `orca.yml`. What makes it a HITL step is the prompt, not the config:

```yaml
states:
  review:
    worker:
      kind: claude-code
      prompt: prompts/get_approval.md.j2
      timeout: 7200
      inactivity_timeout: 3600
    on:
      approved: { target: implement }
      rejected: { target: done }
```

## Conversation Flow

1. **State machine reaches a HITL state.** The orchestrator dispatches a `claude-code` worker as usual.
2. **Orchestrator spawns Claude Code** in a tmux session. The shared `slack-hitl` MCP server URL is passed so Claude Code can access Slack tools. Slack creds from `orca.yml` are already available to the MCP server.
3. **Claude Code reads its prompt** and calls `slack_start_conversation` to DM the target user.
4. **Multi-turn conversation:** Claude Code loops — sending messages, waiting for replies, interpreting responses, asking follow-ups — until it determines it has enough information.
5. **Claude Code writes `result.json`** with the structured result and exits.
6. **Orchestrator reads the result** and advances the state machine.

## Timeouts

Two layers:

| Layer | Scope | Default | Configured in |
|-------|-------|---------|---------------|
| `slack_wait_for_reply` timeout | Per-wait: how long to wait for a single reply | 1 hour | Tool param `timeout_seconds` |
| Worker `inactivity_timeout` | Whole step: kills the tmux session if no stdout activity | From `orca.yml` | `states.<name>.worker.inactivity_timeout` |

If `slack_wait_for_reply` times out, Claude Code can decide to retry (send a nudge) or give up and write a failure result. If the worker-level timeout fires, the orchestrator kills the session and treats it as a `WorkerFailure`.

## Error Handling

- **Slack connection drops:** The Socket Mode SDK reconnects automatically. Active waits survive reconnections.
- **User never replies:** The per-wait timeout fires. Claude Code can nudge or fail gracefully.
- **Multiple concurrent HITL sessions:** Each gets its own thread. The MCP server routes by `(channel, thread_ts)` tuple. No cross-talk.
- **MCP server crashes:** The orchestrator monitors the subprocess. On unexpected exit, it restarts the server and logs a warning. Active waits are lost — affected workers receive tool call errors from the MCP client, and the worker-level inactivity timeout eventually kills those sessions (treated as `WorkerFailure`).

## Prompt Template Example

```jinja2
You are collecting approval for a proposed approach.

Issue: {{ issue.title }}
Proposed approach: {{ issue.approach }}

Use slack_start_conversation to DM user {{ issue.assignee_slack_id }}.
Explain the proposed approach clearly and ask if they approve.
Use slack_wait_for_reply to receive their response.

If they have questions, answer them using the issue context.
Continue the conversation until you have a clear decision.

When done, write your result to {{ result_path }}.

Result format:
{{ result_format | tojson }}
```

## Orchestrator Changes

1. **Startup:** If `integrations.slack` is present in `orca.yml`, start the `slack-hitl` MCP server subprocess. Record its SSE URL.
2. **Worker dispatch:** Pass the MCP server URL to Claude Code workers (via CLI flag or MCP config file).
3. **Shutdown:** Stop the MCP server subprocess on orchestrator exit.
