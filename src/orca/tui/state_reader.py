from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiohttp

from orca.engine.types import State


class StateReader:
    """Reads orchestrator state and sessions from disk with mtime-based change detection."""

    def __init__(self, run_dir: Path) -> None:
        self._state_path = run_dir / "state.json"
        self._sessions_path = run_dir / "sessions.json"
        self._last_mtime: float = 0.0
        self._sessions: list[dict[str, Any]] = []

    @property
    def last_mtime(self) -> float:
        return self._last_mtime

    def read(self) -> tuple[State, list[dict[str, Any]]] | None:
        """Read state and sessions. Returns None if nothing changed.

        Also returns None on OSError (file deleted between exists() and
        read_text()) or torn JSON from foreign writers — without consuming
        the mtime, so the next good write is still picked up.
        """
        try:
            if not self._state_path.exists():
                return None

            state_mtime = self._state_path.stat().st_mtime
            sessions_mtime = self._sessions_path.stat().st_mtime if self._sessions_path.exists() else 0.0
            latest_mtime = max(state_mtime, sessions_mtime)

            if latest_mtime == self._last_mtime:
                return None

            data = json.loads(self._state_path.read_text())
            state = State.from_dict(data)

            sessions = json.loads(self._sessions_path.read_text()) if self._sessions_path.exists() else []
        except (OSError, json.JSONDecodeError):
            return None

        self._last_mtime = latest_mtime
        self._sessions = sessions
        return state, self._sessions

    @property
    def sessions(self) -> list[dict[str, Any]]:
        return self._sessions

    def reset(self) -> None:
        self._last_mtime = 0.0


class DaemonStateReader:
    """Reads orchestrator state from the daemon HTTP API."""

    def __init__(self, session: aiohttp.ClientSession, run_id: str) -> None:
        self._session = session
        self._run_id = run_id
        self._last_state_dict: dict[str, Any] | None = None
        self._sessions: list[dict[str, Any]] = []
        self._run_status: str = ""
        self._unreachable: bool = False

    async def read(self) -> tuple[State, list[dict[str, Any]]] | None:
        """Fetch state from daemon. Returns None if unchanged or unreachable.

        Connection errors (daemon died mid-session) set `unreachable` instead
        of propagating — a raised exception inside a Textual interval callback
        would crash the whole app.
        """
        try:
            async with self._session.get(f"http://localhost/api/runs/{self._run_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, OSError, TimeoutError):
            self._unreachable = True
            return None
        self._unreachable = False
        state_dict = data.get("state")
        sessions = data.get("sessions", [])
        self._run_status = str(data.get("status", ""))
        if state_dict == self._last_state_dict and sessions == self._sessions:
            return None
        self._last_state_dict = state_dict
        self._sessions = sessions
        state = State.from_dict(state_dict)
        return state, self._sessions

    @property
    def sessions(self) -> list[dict[str, Any]]:
        return self._sessions

    @property
    def run_status(self) -> str:
        return self._run_status

    @property
    def unreachable(self) -> bool:
        return self._unreachable

    def reset(self) -> None:
        self._last_state_dict = None
