from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from orca.daemon.lifecycle import pidfile_path, write_browser_port, write_pidfile, write_root_marker
from orca.daemon.server import _pick_free_port, _port_is_free, _resolve_browser_port


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


class TestPortIsFree:
    def test_returns_true_for_free_port(self) -> None:
        free = _pick_free_port()
        # Tiny race window — but on localhost with a freshly-kernel-picked port, it's safe.
        assert _port_is_free(free) is True

    def test_returns_false_for_bound_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            bound_port = s.getsockname()[1]
            assert _port_is_free(bound_port) is False


class TestResolveBrowserPort:
    @pytest.mark.usefixtures("fake_home")
    def test_none_passes_through(self) -> None:
        port, msg = _resolve_browser_port(None)
        assert port is None
        assert msg is None

    @pytest.mark.usefixtures("fake_home")
    def test_free_port_returned_as_is(self) -> None:
        free = _pick_free_port()
        port, msg = _resolve_browser_port(free)
        assert port == free
        assert msg is None

    @pytest.mark.usefixtures("fake_home")
    def test_busy_port_falls_back_and_logs(self) -> None:
        # Hold a port so it's busy.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            busy = held.getsockname()[1]
            port, msg = _resolve_browser_port(busy)
            assert port is not None
            assert port != busy
            assert msg is not None
            assert str(busy) in msg
            assert "ORCA_DAEMON_TCP_PORT" in msg

    @pytest.mark.usefixtures("fake_home")
    def test_busy_port_names_holder_when_known(self, tmp_path: Path) -> None:
        # Register a fake live daemon for a held port — message should name its repo.
        repo = tmp_path / "other-repo"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            busy = held.getsockname()[1]
            write_root_marker(repo)
            write_browser_port(repo, busy)
            write_pidfile(pidfile_path(repo), os.getpid())
            _, msg = _resolve_browser_port(busy)
            assert msg is not None
            assert str(repo) in msg
