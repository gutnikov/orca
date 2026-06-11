"""Tests for the shared daemon HTTP helper (src/orca/cli/_http.py)."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from orca.cli._http import DAEMON_UNREACHABLE_MSG, DaemonResponse, daemon_request


@pytest.fixture()
def sock_dir() -> Iterator[Path]:
    """Short-path temp dir — AF_UNIX socket paths are length-limited on macOS."""
    path = Path(tempfile.mkdtemp(prefix="orca-sock-", dir="/tmp"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class TestDaemonResponse:
    def test_json_parses_valid_body(self) -> None:
        resp = DaemonResponse(200, '{"run_id": "r1"}')
        assert resp.json() == {"run_id": "r1"}

    def test_json_returns_none_for_plain_text(self) -> None:
        resp = DaemonResponse(500, "Internal Server Error")
        assert resp.json() is None

    def test_error_prefers_json_error_field(self) -> None:
        resp = DaemonResponse(404, '{"error": "run not found"}')
        assert resp.error() == "run not found"

    def test_error_falls_back_to_plain_text(self) -> None:
        resp = DaemonResponse(500, "Internal Server Error")
        assert resp.error() == "Internal Server Error"

    def test_error_falls_back_to_status_when_empty(self) -> None:
        resp = DaemonResponse(502, "")
        assert resp.error() == "HTTP 502"


async def _serve_once(sock_path: Path, raw_response: bytes) -> asyncio.AbstractServer:
    """Tiny unix-socket HTTP server returning one canned response."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()  # request line; rest is ignored
        writer.write(raw_response)
        await writer.drain()
        writer.close()

    return await asyncio.start_unix_server(handle, path=str(sock_path))


class TestDaemonRequest:
    @pytest.mark.asyncio()
    async def test_connection_error_exits_with_clean_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sock = tmp_path / "missing.sock"
        with pytest.raises(SystemExit) as exc_info:
            await daemon_request(sock, "GET", "/api/runs")
        assert exc_info.value.code == 1
        assert DAEMON_UNREACHABLE_MSG in capsys.readouterr().err

    @pytest.mark.asyncio()
    async def test_plain_text_error_body_does_not_raise(self, sock_dir: Path) -> None:
        sock = sock_dir / "daemon.sock"
        body = b"Internal Server Error"
        raw = b"HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n%s" % (
            len(body),
            body,
        )
        server = await _serve_once(sock, raw)
        try:
            resp = await daemon_request(sock, "GET", "/api/runs")
        finally:
            server.close()
            await server.wait_closed()
        assert resp.status == 500
        assert resp.error() == "Internal Server Error"

    @pytest.mark.asyncio()
    async def test_json_body_round_trips(self, sock_dir: Path) -> None:
        sock = sock_dir / "daemon.sock"
        body = b'{"run_id": "main:default"}'
        raw = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (
            len(body),
            body,
        )
        server = await _serve_once(sock, raw)
        try:
            resp = await daemon_request(sock, "POST", "/api/runs/start", json_body={"task_file": "t.md"})
        finally:
            server.close()
            await server.wait_closed()
        assert resp.status == 200
        assert resp.json() == {"run_id": "main:default"}
