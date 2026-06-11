from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.state_reader import DaemonStateReader


def _make_state_dict() -> dict[str, object]:
    return State(
        issues={
            "issue-1": Issue(
                type="default",
                fields={"title": "Test Issue", "description": "A test issue"},
                state="triage",
                worker_active=False,
                decomposed_from=None,
                depends_on=[],
                event_log=[
                    EventLogEntry(
                        timestamp="2026-01-01T00:00:00+00:00",
                        type="created",
                        data={},
                    )
                ],
            )
        },
        worker_queues={},
    ).to_dict()


def _mock_session(state_dict: dict[str, object] | None = None, status: int = 200) -> MagicMock:
    """Create a mock aiohttp.ClientSession with a .get() context manager."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value={"state": state_dict})

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


class TestDaemonStateReader:
    @pytest.mark.asyncio()
    async def test_read_returns_state_from_http(self) -> None:
        state_dict = _make_state_dict()
        session = _mock_session(state_dict)
        reader = DaemonStateReader(session, "run-123")

        result = await reader.read()

        assert result is not None
        state, sessions = result
        assert "issue-1" in state.issues
        assert state.issues["issue-1"].fields["title"] == "Test Issue"
        assert sessions == []
        session.get.assert_called_once_with("http://localhost/api/runs/run-123")

    @pytest.mark.asyncio()
    async def test_read_returns_none_when_unchanged(self) -> None:
        state_dict = _make_state_dict()
        session = _mock_session(state_dict)
        reader = DaemonStateReader(session, "run-123")

        first = await reader.read()
        assert first is not None

        second = await reader.read()
        assert second is None

    @pytest.mark.asyncio()
    async def test_read_returns_none_on_http_error(self) -> None:
        session = _mock_session(status=500)
        reader = DaemonStateReader(session, "run-123")

        result = await reader.read()
        assert result is None

    @pytest.mark.asyncio()
    async def test_reset_allows_re_read(self) -> None:
        state_dict = _make_state_dict()
        session = _mock_session(state_dict)
        reader = DaemonStateReader(session, "run-123")

        first = await reader.read()
        assert first is not None

        second = await reader.read()
        assert second is None

        reader.reset()

        third = await reader.read()
        assert third is not None

    @pytest.mark.asyncio()
    async def test_sessions_property_returns_empty_list(self) -> None:
        session = _mock_session()
        reader = DaemonStateReader(session, "run-123")
        assert reader.sessions == []

    @pytest.mark.asyncio()
    async def test_read_returns_none_when_daemon_unreachable(self) -> None:
        """A connection error mid-session must not crash the TUI poll loop."""
        session = MagicMock()
        session.get = MagicMock(side_effect=aiohttp.ClientConnectionError("daemon died"))
        reader = DaemonStateReader(session, "run-123")

        result = await reader.read()

        assert result is None
        assert reader.unreachable is True

    @pytest.mark.asyncio()
    async def test_unreachable_clears_after_successful_read(self) -> None:
        session = MagicMock()
        session.get = MagicMock(side_effect=aiohttp.ClientConnectionError("daemon died"))
        reader = DaemonStateReader(session, "run-123")
        await reader.read()
        assert reader.unreachable is True

        # Daemon comes back: subsequent reads succeed and clear the flag.
        reader._session = _mock_session(_make_state_dict())

        result = await reader.read()
        assert result is not None
        assert reader.unreachable is False
