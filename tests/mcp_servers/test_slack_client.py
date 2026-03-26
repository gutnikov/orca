from __future__ import annotations

import asyncio
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
        await slack_client._message_queues[key].put({"text": "Looks good", "user": "U999", "ts": "1234567891.000000"})
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
