"""Shared HTTP helper for CLI commands that talk to the daemon.

Centralizes two failure modes every daemon-talking command shares:

- the daemon dying between the liveness check and the request
  (``aiohttp.ClientError`` / ``OSError``), which should print a clean
  message instead of a traceback;
- non-JSON error bodies (e.g. Starlette plain-text 500s), which would
  make ``resp.json()`` raise ``ContentTypeError``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

import aiohttp

DAEMON_UNREACHABLE_MSG = "Error: orca daemon unreachable — is it running? try `orca daemon start`"


class DaemonResponse(NamedTuple):
    """Status and raw body of a daemon API response."""

    status: int
    text: str

    def json(self) -> Any:
        """Parsed JSON body, or None when the body is not valid JSON."""
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            return None

    def error(self) -> str:
        """Best-effort error message: JSON 'error' field, raw text, or HTTP status."""
        body = self.json()
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])
        if body is not None and not isinstance(body, dict):
            return json.dumps(body)
        return self.text.strip() or f"HTTP {self.status}"


async def daemon_request(
    sock: Path,
    method: str,
    path: str,
    *,
    json_body: Any = None,
) -> DaemonResponse:
    """Perform one request against the daemon's unix socket.

    On connection failure (daemon died mid-command) prints a clean error
    and exits nonzero instead of dumping a raw traceback.
    """
    connector = aiohttp.UnixConnector(path=str(sock))
    try:
        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.request(method, f"http://localhost{path}", json=json_body) as resp,
        ):
            return DaemonResponse(resp.status, await resp.text())
    except (aiohttp.ClientError, OSError, TimeoutError):
        print(DAEMON_UNREACHABLE_MSG, file=sys.stderr)
        raise SystemExit(1) from None
