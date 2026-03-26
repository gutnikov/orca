# Slack HITL MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an MCP server that gives Claude Code workers the ability to conduct multi-turn Slack DM conversations with humans, enabling human-in-the-loop workflow steps.

**Architecture:** A shared MCP server (`slack-hitl`) runs as a subprocess of the orchestrator, connecting to Slack via Socket Mode. It exposes three tools (`slack_start_conversation`, `slack_send_message`, `slack_wait_for_reply`) over SSE transport. Claude Code workers connect to it via URL. Thread-per-conversation design keeps concurrent HITL sessions isolated.

**Tech Stack:** Python 3.12, `slack_sdk` (Socket Mode async), `mcp` (MCP Python SDK), `starlette`/`sse-starlette` (SSE transport)

---

## File Structure

```
src/orca/mcp_servers/                  # New package
    __init__.py
    slack_hitl/                        # New package
        __init__.py
        server.py                      # MCP server: tool definitions, SSE endpoint
        slack_client.py                # Slack Socket Mode wrapper, message routing

src/orca/orchestrator/config_types.py  # New: integrations config types
src/orca/orchestrator/runner.py        # Modify: parse integrations, start/stop MCP server
src/orca/orchestrator/orchestrator.py  # Modify: pass MCP server URL to workers
src/orca/orchestrator/worker.py        # Modify: accept env param, pass to pty session
src/orca/orchestrator/pty_session.py   # Modify: pass env vars to tmux session

tests/mcp_servers/__init__.py
tests/mcp_servers/test_slack_client.py # Unit tests for Slack client wrapper
tests/mcp_servers/test_server.py       # Unit tests for MCP server tools
tests/mcp_servers/test_integration.py  # End-to-end integration test
tests/orchestrator/test_config_types.py # Tests for integrations config parsing
```

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add slack_sdk, mcp, starlette, and uvicorn to pyproject.toml**

```toml
dependencies = [
    "jinja2>=3.1.6",
    "mcp>=1.0",
    "pyyaml>=6.0.3",
    "slack-sdk>=3.33",
    "starlette>=0.41",
    "textual>=1.0",
    "uvicorn>=0.34",
]
```

- [ ] **Step 2: Run uv sync**

Run: `uv sync`
Expected: Dependencies install successfully.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(slack-hitl): add slack_sdk, mcp, starlette, uvicorn dependencies"
```

---

### Task 2: Integrations config parsing

Parse the `integrations.slack` section from `orca.yml` and expose it as a typed dataclass.

**Files:**
- Create: `src/orca/orchestrator/config_types.py`
- Test: `tests/orchestrator/test_config_types.py`

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_config_types.py`:

```python
from __future__ import annotations

import pytest

from orca.orchestrator.config_types import parse_integrations


class TestParseIntegrations:
    def test_literal_tokens(self) -> None:
        raw = {"slack": {"bot_token": "xoxb-123", "app_token": "xapp-456"}}
        result = parse_integrations(raw)
        assert result.slack is not None
        assert result.slack.bot_token == "xoxb-123"
        assert result.slack.app_token == "xapp-456"

    def test_env_var_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_BOT_TOKEN", "xoxb-from-env")
        monkeypatch.setenv("MY_APP_TOKEN", "xapp-from-env")
        raw = {"slack": {"bot_token_env": "MY_BOT_TOKEN", "app_token_env": "MY_APP_TOKEN"}}
        result = parse_integrations(raw)
        assert result.slack is not None
        assert result.slack.bot_token == "xoxb-from-env"
        assert result.slack.app_token == "xapp-from-env"

    def test_missing_env_var_raises(self) -> None:
        raw = {"slack": {"bot_token_env": "NONEXISTENT_VAR", "app_token_env": "ALSO_MISSING"}}
        with pytest.raises(ValueError, match="NONEXISTENT_VAR"):
            parse_integrations(raw)

    def test_no_slack_section(self) -> None:
        result = parse_integrations({})
        assert result.slack is None

    def test_none_input(self) -> None:
        result = parse_integrations(None)
        assert result.slack is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_config_types.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Create `src/orca/orchestrator/config_types.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SlackConfig:
    bot_token: str
    app_token: str


@dataclass(frozen=True)
class IntegrationsConfig:
    slack: SlackConfig | None = None


def _resolve_token(data: dict[str, Any], key: str, env_key: str) -> str:
    """Resolve a token from a literal value or environment variable."""
    literal = data.get(key)
    if literal is not None:
        return str(literal)
    env_var = data.get(env_key)
    if env_var is not None:
        value = os.environ.get(str(env_var))
        if value is None:
            msg = f"Environment variable '{env_var}' (from {env_key}) is not set"
            raise ValueError(msg)
        return value
    msg = f"Either '{key}' or '{env_key}' must be provided"
    raise ValueError(msg)


def parse_integrations(raw: dict[str, Any] | None) -> IntegrationsConfig:
    """Parse the integrations section of orca.yml."""
    if not raw:
        return IntegrationsConfig()

    slack_data = raw.get("slack")
    slack: SlackConfig | None = None
    if slack_data is not None:
        bot_token = _resolve_token(slack_data, "bot_token", "bot_token_env")
        app_token = _resolve_token(slack_data, "app_token", "app_token_env")
        slack = SlackConfig(bot_token=bot_token, app_token=app_token)

    return IntegrationsConfig(slack=slack)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_config_types.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/orchestrator/config_types.py tests/orchestrator/test_config_types.py && uv run mypy src/orca/orchestrator/config_types.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/config_types.py tests/orchestrator/test_config_types.py
git commit -m "feat(slack-hitl): add integrations config parsing"
```

---

### Task 3: Slack client wrapper

Wrap `slack_sdk` to provide a simple async interface for sending DMs and waiting for threaded replies.

**Files:**
- Create: `src/orca/mcp_servers/__init__.py`
- Create: `src/orca/mcp_servers/slack_hitl/__init__.py`
- Create: `src/orca/mcp_servers/slack_hitl/slack_client.py`
- Test: `tests/mcp_servers/__init__.py`
- Test: `tests/mcp_servers/test_slack_client.py`

- [ ] **Step 1: Create package init files**

Create empty `src/orca/mcp_servers/__init__.py`, `src/orca/mcp_servers/slack_hitl/__init__.py`, `tests/mcp_servers/__init__.py`.

- [ ] **Step 2: Write the failing test**

Create `tests/mcp_servers/test_slack_client.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from orca.mcp_servers.slack_hitl.slack_client import SlackHitlClient


@pytest.fixture
def mock_web_client() -> MagicMock:
    client = MagicMock()
    client.conversations_open = AsyncMock(return_value={"channel": {"id": "D123"}})
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234567890.123456"})
    return client


@pytest.fixture
def slack_client(mock_web_client: MagicMock) -> SlackHitlClient:
    client = SlackHitlClient.__new__(SlackHitlClient)
    client._web_client = mock_web_client
    client._message_queues = {}
    return client


@pytest.mark.asyncio()
class TestSlackHitlClient:
    async def test_start_conversation(self, slack_client: SlackHitlClient, mock_web_client: MagicMock) -> None:
        result = await slack_client.start_conversation("U999", "Hello!")
        assert result["channel"] == "D123"
        assert result["thread_ts"] == "1234567890.123456"
        mock_web_client.conversations_open.assert_called_once_with(users=["U999"])
        mock_web_client.chat_postMessage.assert_called_once_with(channel="D123", text="Hello!")

    async def test_send_message(self, slack_client: SlackHitlClient, mock_web_client: MagicMock) -> None:
        result = await slack_client.send_message("D123", "1234567890.123456", "Follow-up")
        assert result["ts"] == "1234567890.123456"
        mock_web_client.chat_postMessage.assert_called_once_with(
            channel="D123", thread_ts="1234567890.123456", text="Follow-up"
        )

    async def test_wait_for_reply_receives_message(self, slack_client: SlackHitlClient) -> None:
        key = ("D123", "1234567890.123456")
        slack_client._message_queues[key] = asyncio.Queue()
        await slack_client._message_queues[key].put(
            {"text": "Looks good", "user": "U999", "ts": "1234567891.000000"}
        )
        result = await slack_client.wait_for_reply("D123", "1234567890.123456", timeout_seconds=5)
        assert result["text"] == "Looks good"

    async def test_wait_for_reply_timeout(self, slack_client: SlackHitlClient) -> None:
        key = ("D123", "1234567890.123456")
        slack_client._message_queues[key] = asyncio.Queue()
        with pytest.raises(TimeoutError, match="No reply"):
            await slack_client.wait_for_reply("D123", "1234567890.123456", timeout_seconds=0.1)

    async def test_route_message_to_waiting_queue(self, slack_client: SlackHitlClient) -> None:
        key = ("D123", "1234567890.123456")
        slack_client._message_queues[key] = asyncio.Queue()
        slack_client.route_message("D123", "1234567890.123456", {"text": "hi", "user": "U1", "ts": "t1"})
        msg = await slack_client._message_queues[key].get()
        assert msg["text"] == "hi"

    async def test_route_message_untracked_thread_ignored(self, slack_client: SlackHitlClient) -> None:
        slack_client.route_message("D999", "9999999999.000000", {"text": "stray", "user": "U1", "ts": "t1"})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/mcp_servers/test_slack_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write minimal implementation**

Create `src/orca/mcp_servers/slack_hitl/slack_client.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


class SlackHitlClient:
    """Wraps Slack Web API for HITL conversations.

    Provides methods to start threaded DM conversations, send messages,
    and wait for replies. Message routing is keyed by (channel, thread_ts).
    """

    def __init__(self, bot_token: str) -> None:
        self._web_client = AsyncWebClient(token=bot_token)
        self._message_queues: dict[tuple[str, str], asyncio.Queue[dict[str, Any]]] = {}

    async def start_conversation(self, user_id: str, text: str) -> dict[str, str]:
        """Open a DM and post the initial message. Returns channel and thread_ts."""
        resp = await self._web_client.conversations_open(users=[user_id])
        channel_id: str = resp["channel"]["id"]

        msg_resp = await self._web_client.chat_postMessage(channel=channel_id, text=text)
        thread_ts: str = msg_resp["ts"]

        key = (channel_id, thread_ts)
        self._message_queues[key] = asyncio.Queue()

        return {"channel": channel_id, "thread_ts": thread_ts}

    async def send_message(self, channel: str, thread_ts: str, text: str) -> dict[str, str]:
        """Post a follow-up message in an existing thread."""
        resp = await self._web_client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
        return {"ts": resp["ts"]}

    async def wait_for_reply(self, channel: str, thread_ts: str, timeout_seconds: int = 3600) -> dict[str, str]:
        """Block until a message arrives in the specified thread, or timeout."""
        key = (channel, thread_ts)
        if key not in self._message_queues:
            self._message_queues[key] = asyncio.Queue()

        try:
            msg: dict[str, Any] = await asyncio.wait_for(self._message_queues[key].get(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"No reply in channel={channel} thread={thread_ts} after {timeout_seconds}s"
            ) from None

        return {"text": msg["text"], "user": msg["user"], "ts": msg["ts"]}

    def route_message(self, channel: str, thread_ts: str, message: dict[str, Any]) -> None:
        """Route an incoming Slack message to the appropriate waiting queue."""
        key = (channel, thread_ts)
        queue = self._message_queues.get(key)
        if queue is None:
            logger.debug("Ignoring message for untracked thread %s/%s", channel, thread_ts)
            return
        queue.put_nowait(message)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/mcp_servers/test_slack_client.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Run linters**

Run: `uv run ruff check src/orca/mcp_servers/ tests/mcp_servers/ && uv run mypy src/orca/mcp_servers/`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add src/orca/mcp_servers/ tests/mcp_servers/
git commit -m "feat(slack-hitl): add Slack client wrapper with message routing"
```

---

### Task 4: MCP server with tool definitions

Build the MCP server that exposes the three Slack tools over SSE transport.

**Files:**
- Create: `src/orca/mcp_servers/slack_hitl/server.py`
- Test: `tests/mcp_servers/test_server.py`

- [ ] **Step 1: Write the failing test**

Create `tests/mcp_servers/test_server.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from orca.mcp_servers.slack_hitl.server import create_server


@pytest.fixture
def mock_slack_client() -> MagicMock:
    client = MagicMock()
    client.start_conversation = AsyncMock(return_value={"channel": "D123", "thread_ts": "ts1"})
    client.send_message = AsyncMock(return_value={"ts": "ts2"})
    client.wait_for_reply = AsyncMock(return_value={"text": "ok", "user": "U1", "ts": "ts3"})
    return client


class TestCreateServer:
    def test_server_has_tools(self, mock_slack_client: MagicMock) -> None:
        server = create_server(mock_slack_client)
        assert server is not None


@pytest.mark.asyncio()
class TestServerTools:
    async def test_lists_all_three_tools(self, mock_slack_client: MagicMock) -> None:
        server = create_server(mock_slack_client)
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"slack_start_conversation", "slack_send_message", "slack_wait_for_reply"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp_servers/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Create `src/orca/mcp_servers/slack_hitl/server.py`:

```python
from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from orca.mcp_servers.slack_hitl.slack_client import SlackHitlClient

logger = logging.getLogger(__name__)


def create_server(slack_client: SlackHitlClient) -> Server:
    """Create an MCP server with Slack HITL tools."""
    server = Server("slack-hitl")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="slack_start_conversation",
                description=(
                    "Open a DM with a Slack user and post the initial message. "
                    "Returns channel and thread_ts for subsequent calls."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "description": "Slack user ID (e.g. U12345)"},
                        "text": {"type": "string", "description": "Initial message text"},
                    },
                    "required": ["user_id", "text"],
                },
            ),
            Tool(
                name="slack_send_message",
                description="Post a follow-up message in an existing conversation thread.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Slack channel ID from start_conversation"},
                        "thread_ts": {
                            "type": "string",
                            "description": "Thread timestamp from start_conversation",
                        },
                        "text": {"type": "string", "description": "Message text"},
                    },
                    "required": ["channel", "thread_ts", "text"],
                },
            ),
            Tool(
                name="slack_wait_for_reply",
                description=(
                    "Wait for the human to reply in the specified thread. "
                    "Blocks until a reply arrives or timeout."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Slack channel ID"},
                        "thread_ts": {"type": "string", "description": "Thread timestamp"},
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "Max seconds to wait (default 3600)",
                            "default": 3600,
                        },
                    },
                    "required": ["channel", "thread_ts"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "slack_start_conversation":
            result = await slack_client.start_conversation(
                user_id=arguments["user_id"],
                text=arguments["text"],
            )
            return [TextContent(type="text", text=json.dumps(result))]

        if name == "slack_send_message":
            result = await slack_client.send_message(
                channel=arguments["channel"],
                thread_ts=arguments["thread_ts"],
                text=arguments["text"],
            )
            return [TextContent(type="text", text=json.dumps(result))]

        if name == "slack_wait_for_reply":
            timeout = arguments.get("timeout_seconds", 3600)
            try:
                result = await slack_client.wait_for_reply(
                    channel=arguments["channel"],
                    thread_ts=arguments["thread_ts"],
                    timeout_seconds=timeout,
                )
                return [TextContent(type="text", text=json.dumps(result))]
            except TimeoutError as e:
                return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    return server


async def run_server(bot_token: str, app_token: str, host: str, port: int) -> None:
    """Start the MCP server with SSE transport and Slack Socket Mode."""
    from mcp.server.sse import SseServerTransport
    from slack_sdk.socket_mode.aio import AsyncSocketModeClient
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    import uvicorn

    slack_client = SlackHitlClient(bot_token)
    server = create_server(slack_client)

    # Set up Socket Mode to receive Slack events
    socket_client = AsyncSocketModeClient(app_token=app_token, web_client=slack_client._web_client)

    async def _handle_socket_event(client: Any, req: Any) -> None:
        """Route incoming Slack message events to the appropriate thread queue."""
        payload = req.payload
        event = payload.get("event", {})
        if event.get("type") == "message" and event.get("subtype") is None:
            channel = event.get("channel", "")
            thread_ts = event.get("thread_ts", "")
            if thread_ts:
                slack_client.route_message(
                    channel,
                    thread_ts,
                    {"text": event.get("text", ""), "user": event.get("user", ""), "ts": event.get("ts", "")},
                )
        await req.ack()

    socket_client.socket_mode_request_listeners.append(_handle_socket_event)

    # Set up SSE transport
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Any) -> Any:
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    # Bind to get the actual port (when port=0)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    actual_port = sock.getsockname()[1]
    sock.close()

    # Print port for orchestrator to discover
    print(actual_port, flush=True)

    # Start Socket Mode in background
    await socket_client.connect()

    config = uvicorn.Config(app, host=host, port=actual_port, log_level="warning")
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()


def main() -> None:
    """CLI entry point for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(prog="slack-hitl-mcp", description="Slack HITL MCP Server")
    parser.add_argument("--bot-token", required=True, help="Slack bot token (xoxb-...)")
    parser.add_argument("--app-token", required=True, help="Slack app token (xapp-...)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind SSE server")
    parser.add_argument("--port", type=int, default=0, help="Port for SSE server (0 = auto)")
    args = parser.parse_args()

    asyncio.run(run_server(args.bot_token, args.app_token, args.host, args.port))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp_servers/test_server.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/mcp_servers/slack_hitl/server.py tests/mcp_servers/test_server.py && uv run mypy src/orca/mcp_servers/slack_hitl/server.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/mcp_servers/slack_hitl/server.py tests/mcp_servers/test_server.py
git commit -m "feat(slack-hitl): add MCP server with tool definitions and SSE transport"
```

---

### Task 5: Pass environment variables through tmux sessions

The `TmuxSession.spawn` method accepts an `env` parameter but doesn't use it. Wire it so the orchestrator can pass env vars (like `SLACK_HITL_MCP_URL`) to workers.

**Files:**
- Modify: `src/orca/orchestrator/pty_session.py:44-87`

- [ ] **Step 1: Update TmuxSession.spawn to prepend env exports**

In `src/orca/orchestrator/pty_session.py`, in the `spawn` method, after constructing `full_cmd` and before building `tmux_args`, add:

```python
        # Prepend env vars as shell exports
        if env:
            exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            full_cmd = f"export {exports}; {full_cmd}"
```

This goes after the `stdin_data` block (line ~60) and before the `tmux_args` list (line ~62).

- [ ] **Step 2: Run existing tests to verify nothing broke**

Run: `uv run pytest tests/orchestrator/test_pty_session.py -v`
Expected: All existing tests PASS

- [ ] **Step 3: Run linters**

Run: `uv run ruff check src/orca/orchestrator/pty_session.py && uv run mypy src/orca/orchestrator/pty_session.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/orca/orchestrator/pty_session.py
git commit -m "feat(slack-hitl): pass env vars through tmux sessions via shell exports"
```

---

### Task 6: Worker accepts and passes env to pty session

Add `env` parameter to the `Worker` protocol and `ClaudeCodeWorker`, forwarding it to `pty_session.spawn`.

**Files:**
- Modify: `src/orca/orchestrator/worker.py`
- Modify: `tests/orchestrator/test_worker.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/orchestrator/test_worker.py`:

```python
    async def test_env_passed_to_pty_session(self, tmp_path: Path) -> None:
        """Verify env dict is forwarded to pty_session.spawn."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
        pty = _make_mock_pty(exit_code=0, write_result=valid_result, result_path=result_path)

        env = {"SLACK_HITL_MCP_URL": "http://127.0.0.1:9999/sse"}
        worker = ClaudeCodeWorker(repo_root=tmp_path)
        await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty, env=env)

        # Verify env was passed to spawn
        pty.spawn.assert_called_once()
        call_kwargs = pty.spawn.call_args
        assert call_kwargs.kwargs.get("env") == env or call_kwargs[1].get("env") == env
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestClaudeCodeWorker::test_env_passed_to_pty_session -v`
Expected: FAIL (env parameter not accepted yet)

- [ ] **Step 3: Update Worker protocol and ClaudeCodeWorker**

In `src/orca/orchestrator/worker.py`:

Update the `Worker` protocol:
```python
class Worker(Protocol):
    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: PtySession | None = None,
        env: dict[str, str] | None = None,
    ) -> WorkerOutcome: ...
```

Update `ClaudeCodeWorker.execute` to accept `env` and pass it to `pty_session.spawn`:
```python
    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: PtySession | None = None,
        env: dict[str, str] | None = None,
    ) -> WorkerOutcome:
```

And in the spawn call:
```python
        await pty_session.spawn(
            "claude",
            ["--dangerously-skip-permissions", "--max-turns", "50"],
            cwd=workdir,
            stdin_data=prompt.encode(),
            env=env,
        )
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/orchestrator/test_worker.py -v`
Expected: All tests PASS (including new test)

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/orchestrator/worker.py && uv run mypy src/orca/orchestrator/worker.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/worker.py tests/orchestrator/test_worker.py
git commit -m "feat(slack-hitl): worker accepts env dict and passes to pty session"
```

---

### Task 7: Orchestrator starts/stops MCP server and passes URL to workers

Wire the orchestrator to start the `slack-hitl` MCP server on startup (when Slack is configured), pass its URL to workers, and shut it down on exit.

**Files:**
- Modify: `src/orca/orchestrator/runner.py`
- Modify: `src/orca/orchestrator/orchestrator.py`

- [ ] **Step 1: Add slack_mcp_url to Orchestrator.__init__**

In `src/orca/orchestrator/orchestrator.py`, add parameter `slack_mcp_url: str | None = None` to `__init__` and store as `self._slack_mcp_url`.

- [ ] **Step 2: Pass env to worker in _run_worker**

In `src/orca/orchestrator/orchestrator.py`, in the `_run_worker` method, build an env dict and pass it to `worker.execute`:

After line 287 (`inactivity_timeout = ...`), add:
```python
        worker_env: dict[str, str] = {}
        if self._slack_mcp_url:
            worker_env["SLACK_HITL_MCP_URL"] = self._slack_mcp_url
```

Update the `worker.execute` call to include `env=worker_env or None`.

- [ ] **Step 3: Parse integrations and manage MCP server in runner.py**

In `src/orca/orchestrator/runner.py`:

Add import:
```python
import yaml
from orca.orchestrator.config_types import IntegrationsConfig, SlackConfig, parse_integrations
```

In the `run()` function, after `config = parse_config(config_path.read_text())`, add:
```python
    raw_config: dict[str, Any] = yaml.safe_load(config_path.read_text())
    integrations = parse_integrations(raw_config.get("integrations"))
```

Add a helper function:
```python
async def _start_slack_mcp_server(slack_config: SlackConfig) -> tuple[asyncio.subprocess.Process, str]:
    """Start the slack-hitl MCP server subprocess, return (process, sse_url)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "orca.mcp_servers.slack_hitl.server",
        "--bot-token",
        slack_config.bot_token,
        "--app-token",
        slack_config.app_token,
        "--port",
        "0",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
    port = int(line.decode().strip())
    return proc, f"http://127.0.0.1:{port}/sse"
```

In `run()`, before constructing the Orchestrator, start the MCP server if configured:
```python
    slack_mcp_proc: asyncio.subprocess.Process | None = None
    slack_mcp_url: str | None = None
    if integrations.slack is not None:
        slack_mcp_proc, slack_mcp_url = await _start_slack_mcp_server(integrations.slack)
        logger.info("Slack HITL MCP server started", extra={"event": "slack_mcp_started", "url": slack_mcp_url})
```

Pass `slack_mcp_url=slack_mcp_url` to the `Orchestrator` constructor.

In the `finally` block (or after `orchestrator.run`), clean up:
```python
    if slack_mcp_proc is not None:
        slack_mcp_proc.terminate()
        await slack_mcp_proc.wait()
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/orchestrator/ && uv run mypy src/orca/orchestrator/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/runner.py src/orca/orchestrator/orchestrator.py
git commit -m "feat(slack-hitl): orchestrator starts MCP server and passes URL to workers"
```

---

### Task 8: Verify config validation is compatible

The config validator hardcodes `kind: claude-code`. Since HITL states use the same worker kind, verify no changes are needed.

**Files:**
- Read: `src/orca/engine/config.py:160-163`

- [ ] **Step 1: Verify**

Line 161: `if state.worker.kind != "claude-code":` — correct. HITL states use `kind: claude-code` with a Slack-oriented prompt. No change needed.

- [ ] **Step 2: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS

---

### Task 9: End-to-end integration test

Wire together config parsing, MCP server, and Slack client with mocked Slack APIs.

**Files:**
- Create: `tests/mcp_servers/test_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/mcp_servers/test_integration.py`:

```python
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from orca.mcp_servers.slack_hitl.server import create_server
from orca.mcp_servers.slack_hitl.slack_client import SlackHitlClient
from orca.orchestrator.config_types import parse_integrations


@pytest.fixture
def mock_web_client() -> MagicMock:
    client = MagicMock()
    client.conversations_open = AsyncMock(return_value={"channel": {"id": "D123"}})
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234567890.123456"})
    return client


@pytest.fixture
def slack_client(mock_web_client: MagicMock) -> SlackHitlClient:
    client = SlackHitlClient.__new__(SlackHitlClient)
    client._web_client = mock_web_client
    client._message_queues = {}
    return client


@pytest.mark.asyncio()
class TestEndToEnd:
    async def test_full_conversation_flow(self, slack_client: SlackHitlClient) -> None:
        """Simulate: start conversation -> human replies -> agent reads reply -> sends follow-up."""
        server = create_server(slack_client)

        # 1. Start conversation
        start_result = await server.call_tool(
            "slack_start_conversation", {"user_id": "U999", "text": "Need approval on X"}
        )
        data = json.loads(start_result[0].text)
        channel = data["channel"]
        thread_ts = data["thread_ts"]
        assert channel == "D123"

        # 2. Simulate human reply arriving
        slack_client.route_message(channel, thread_ts, {"text": "Approved!", "user": "U999", "ts": "t2"})

        # 3. Agent waits for reply
        wait_result = await server.call_tool(
            "slack_wait_for_reply", {"channel": channel, "thread_ts": thread_ts, "timeout_seconds": 5}
        )
        data = json.loads(wait_result[0].text)
        assert data["text"] == "Approved!"
        assert data["user"] == "U999"

        # 4. Agent sends follow-up
        send_result = await server.call_tool(
            "slack_send_message", {"channel": channel, "thread_ts": thread_ts, "text": "Thanks!"}
        )
        data = json.loads(send_result[0].text)
        assert "ts" in data

    async def test_wait_timeout_returns_error(self, slack_client: SlackHitlClient) -> None:
        """Verify timeout returns error JSON instead of raising."""
        server = create_server(slack_client)

        start_result = await server.call_tool(
            "slack_start_conversation", {"user_id": "U999", "text": "Hello"}
        )
        data = json.loads(start_result[0].text)

        wait_result = await server.call_tool(
            "slack_wait_for_reply",
            {"channel": data["channel"], "thread_ts": data["thread_ts"], "timeout_seconds": 0.1},
        )
        error_data = json.loads(wait_result[0].text)
        assert "error" in error_data

    async def test_config_to_client_flow(self) -> None:
        """Verify integrations config parses correctly for use with SlackHitlClient."""
        raw = {"slack": {"bot_token": "xoxb-test", "app_token": "xapp-test"}}
        config = parse_integrations(raw)
        assert config.slack is not None
        assert config.slack.bot_token == "xoxb-test"
        assert config.slack.app_token == "xapp-test"
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/mcp_servers/test_integration.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Run full test suite and linters**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy src/`
Expected: All tests PASS, no lint or type errors

- [ ] **Step 4: Commit**

```bash
git add tests/mcp_servers/test_integration.py
git commit -m "test(slack-hitl): add end-to-end integration test for HITL conversation flow"
```
