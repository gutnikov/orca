from __future__ import annotations

import json
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
        # call_tool returns (list[ContentBlock], dict); content blocks have a .text attribute
        content_blocks, _ = await server.call_tool(
            "slack_start_conversation", {"user_id": "U999", "text": "Need approval on X"}
        )
        data = json.loads(content_blocks[0].text)
        channel = data["channel"]
        thread_ts = data["thread_ts"]
        assert channel == "D123"

        # 2. Simulate human reply arriving
        slack_client.route_message(channel, thread_ts, {"text": "Approved!", "user": "U999", "ts": "t2"})

        # 3. Agent waits for reply
        content_blocks, _ = await server.call_tool(
            "slack_wait_for_reply", {"channel": channel, "thread_ts": thread_ts, "timeout_seconds": 5}
        )
        data = json.loads(content_blocks[0].text)
        assert data["text"] == "Approved!"
        assert data["user"] == "U999"

        # 4. Agent sends follow-up
        content_blocks, _ = await server.call_tool(
            "slack_send_message", {"channel": channel, "thread_ts": thread_ts, "text": "Thanks!"}
        )
        data = json.loads(content_blocks[0].text)
        assert "ts" in data

    async def test_wait_timeout_returns_error(self, slack_client: SlackHitlClient) -> None:
        """Verify server tool wraps TimeoutError into error JSON instead of raising."""
        # Use a mock client whose wait_for_reply raises TimeoutError, matching real timeout behavior.
        mock_client = MagicMock()
        mock_client.start_conversation = AsyncMock(return_value={"channel": "D123", "thread_ts": "ts1"})
        mock_client.wait_for_reply = AsyncMock(side_effect=TimeoutError("No reply after 0.1s"))

        server = create_server(mock_client)

        content_blocks, _ = await server.call_tool("slack_start_conversation", {"user_id": "U999", "text": "Hello"})
        data = json.loads(content_blocks[0].text)

        content_blocks, _ = await server.call_tool(
            "slack_wait_for_reply",
            {"channel": data["channel"], "thread_ts": data["thread_ts"], "timeout_seconds": 5},
        )
        error_data = json.loads(content_blocks[0].text)
        assert "error" in error_data

    async def test_config_to_client_flow(self) -> None:
        """Verify integrations config parses correctly for use with SlackHitlClient."""
        raw = {"slack": {"bot_token": "xoxb-test", "app_token": "xapp-test"}}
        config = parse_integrations(raw)
        assert config.slack is not None
        assert config.slack.bot_token == "xoxb-test"
        assert config.slack.app_token == "xapp-test"
