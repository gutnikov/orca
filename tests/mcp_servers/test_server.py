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
