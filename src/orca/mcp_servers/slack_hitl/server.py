from __future__ import annotations

import asyncio
import json
import logging
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


async def _connect_socket_mode(slack_client: SlackHitlClient, app_token: str) -> None:
    """Connect Slack Socket Mode to route incoming messages to the client."""
    from slack_sdk.socket_mode.aiohttp import SocketModeClient as AsyncSocketModeClient

    socket_client = AsyncSocketModeClient(app_token=app_token, web_client=slack_client._web_client)

    async def _handle_socket_event(client: Any, req: Any) -> None:
        from slack_sdk.socket_mode.response import SocketModeResponse

        logger.info("Socket Mode event received: type=%s", req.type)
        # Acknowledge immediately to prevent retries
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        payload = req.payload
        event = payload.get("event", {})
        logger.info(
            "Event: type=%s subtype=%s channel=%s thread_ts=%s bot_id=%s",
            event.get("type"),
            event.get("subtype"),
            event.get("channel"),
            event.get("thread_ts"),
            event.get("bot_id"),
        )

        # Only process human messages (ignore bot messages)
        if event.get("type") == "message" and event.get("subtype") is None and not event.get("bot_id"):
            channel = event.get("channel", "")
            thread_ts = event.get("thread_ts")  # None for non-threaded DM replies
            slack_client.route_message(
                channel,
                thread_ts,
                {"text": event.get("text", ""), "user": event.get("user", ""), "ts": event.get("ts", "")},
            )

    socket_client.socket_mode_request_listeners.append(_handle_socket_event)
    await socket_client.connect()


async def run_stdio(bot_token: str, app_token: str) -> None:
    """Run the MCP server over stdio with Slack Socket Mode for message routing."""
    slack_client = SlackHitlClient(bot_token)
    server = create_server(slack_client)

    await _connect_socket_mode(slack_client, app_token)

    await server.run_stdio_async()


def main() -> None:
    """CLI entry point for the MCP server.

    Tokens can be passed via CLI args or environment variables
    (SLACK_BOT_TOKEN, SLACK_APP_TOKEN).
    """
    import argparse
    import os

    parser = argparse.ArgumentParser(prog="slack-hitl-mcp", description="Slack HITL MCP Server")
    parser.add_argument("--bot-token", default=None, help="Slack bot token (xoxb-...)")
    parser.add_argument("--app-token", default=None, help="Slack app token (xapp-...)")
    args = parser.parse_args()

    bot_token = args.bot_token or os.environ.get("SLACK_BOT_TOKEN")
    app_token = args.app_token or os.environ.get("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        parser.error("Slack tokens required via --bot-token/--app-token or SLACK_BOT_TOKEN/SLACK_APP_TOKEN env vars")

    logging.basicConfig(
        filename="/tmp/slack-hitl-mcp.log",
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    asyncio.run(run_stdio(bot_token, app_token))


if __name__ == "__main__":
    main()
