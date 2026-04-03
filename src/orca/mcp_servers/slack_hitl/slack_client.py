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

    async def wait_for_reply(self, channel: str, thread_ts: str, timeout_seconds: float = 3600) -> dict[str, str]:
        """Block until a message arrives in the specified thread, or timeout."""
        key = (channel, thread_ts)
        if key not in self._message_queues:
            self._message_queues[key] = asyncio.Queue()

        try:
            msg: dict[str, Any] = await asyncio.wait_for(self._message_queues[key].get(), timeout=timeout_seconds)
        except TimeoutError:
            raise TimeoutError(f"No reply in channel={channel} thread={thread_ts} after {timeout_seconds}s") from None

        return {"text": msg["text"], "user": msg["user"], "ts": msg["ts"]}

    def route_message(self, channel: str, thread_ts: str | None, message: dict[str, Any]) -> None:
        """Route an incoming Slack message to the appropriate waiting queue.

        If thread_ts is set, match exactly. If None (top-level DM reply),
        match any active conversation in the same channel.
        """
        if thread_ts:
            key = (channel, thread_ts)
            queue = self._message_queues.get(key)
            if queue is not None:
                queue.put_nowait(message)
                return

        # Non-threaded reply — find any active queue for this channel
        for (ch, _ts), queue in self._message_queues.items():
            if ch == channel:
                queue.put_nowait(message)
                return

        logger.debug("Ignoring message for untracked channel/thread %s/%s", channel, thread_ts)
