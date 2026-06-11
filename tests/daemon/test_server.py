from __future__ import annotations

import os
import shutil
import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from orca.daemon.lifecycle import pidfile_path, write_browser_port, write_pidfile, write_root_marker
from orca.daemon.server import _bind_uds, _pick_free_port, _port_is_free, _resolve_browser_port


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


@pytest.fixture()
def short_dir() -> Iterator[Path]:
    """AF_UNIX paths are limited to ~104 chars on macOS; pytest's tmp_path is
    too deep, so bind test sockets under a short /tmp directory instead."""
    d = Path(tempfile.mkdtemp(prefix="orca-uds-", dir="/tmp"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestBindUds:
    def test_socket_is_owner_only(self, short_dir: Path) -> None:
        """The daemon UDS is the privileged control surface — it must be
        bound with 0o600 and live in a 0o700 directory."""
        sock_path = short_dir / "d" / "daemon.sock"
        sock = _bind_uds(sock_path)
        try:
            assert sock_path.exists()
            assert stat.S_IMODE(sock_path.lstat().st_mode) == 0o600
            assert stat.S_IMODE(sock_path.parent.stat().st_mode) == 0o700
        finally:
            sock.close()

    def test_clamps_existing_dir_permissions(self, short_dir: Path) -> None:
        daemon_dir = short_dir / "d"
        daemon_dir.mkdir(parents=True)
        os.chmod(daemon_dir, 0o755)
        sock = _bind_uds(daemon_dir / "daemon.sock")
        try:
            assert stat.S_IMODE(daemon_dir.stat().st_mode) == 0o700
        finally:
            sock.close()


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
