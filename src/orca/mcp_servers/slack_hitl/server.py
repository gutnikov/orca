from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

from mcp.server.fastmcp import FastMCP

from orca.mcp_servers.slack_hitl.slack_client import SlackHitlClient

logger = logging.getLogger(__name__)


def create_server(slack_client: SlackHitlClient) -> FastMCP:
    """Create an MCP server with Slack HITL tools."""
    server = FastMCP("slack-hitl")

    async def slack_start_conversation(user_id: str, text: str) -> str:
        """Open a DM with a Slack user and post the initial message.

        Returns channel and thread_ts for subsequent calls.
        """
        result = await slack_client.start_conversation(user_id=user_id, text=text)
        return json.dumps(result)

    async def slack_send_message(channel: str, thread_ts: str, text: str) -> str:
        """Post a follow-up message in an existing conversation thread."""
        result = await slack_client.send_message(channel=channel, thread_ts=thread_ts, text=text)
        return json.dumps(result)

    async def slack_wait_for_reply(channel: str, thread_ts: str, timeout_seconds: int = 3600) -> str:
        """Wait for the human to reply in the specified thread.

        Blocks until a reply arrives or timeout.
        """
        try:
            result = await slack_client.wait_for_reply(
                channel=channel,
                thread_ts=thread_ts,
                timeout_seconds=timeout_seconds,
            )
            return json.dumps(result)
        except TimeoutError as e:
            return json.dumps({"error": str(e)})

    server.add_tool(slack_start_conversation, name="slack_start_conversation")
    server.add_tool(slack_send_message, name="slack_send_message")
    server.add_tool(slack_wait_for_reply, name="slack_wait_for_reply")

    return server


async def run_server(bot_token: str, app_token: str, host: str, port: int) -> None:
    """Start the MCP server with SSE transport and Slack Socket Mode."""
    import uvicorn

    slack_client = SlackHitlClient(bot_token)
    server = create_server(slack_client)

    from slack_sdk.socket_mode.aio import AsyncSocketModeClient

    socket_client = AsyncSocketModeClient(app_token=app_token, web_client=slack_client._web_client)

    async def _handle_socket_event(client: Any, req: Any) -> None:
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

    app = server.sse_app()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    actual_port = sock.getsockname()[1]
    sock.close()

    print(actual_port, flush=True)

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
