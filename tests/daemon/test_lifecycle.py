from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from orca.daemon.lifecycle import (
    DaemonAlreadyRunningError,
    check_daemon_running,
    cleanup_stale_socket,
    daemon_dir,
    pidfile_path,
    read_pidfile,
    remove_pidfile,
    send_stop_signal,
    socket_path,
    write_pidfile,
)


class TestPidfile:
    def test_write_and_read(self, tmp_path: Path) -> None:
        pf = tmp_path / "daemon.pid"
        write_pidfile(pf, 12345)
        assert read_pidfile(pf) == 12345

    def test_read_missing(self, tmp_path: Path) -> None:
        pf = tmp_path / "daemon.pid"
        assert read_pidfile(pf) is None

    def test_read_invalid_contents(self, tmp_path: Path) -> None:
        pf = tmp_path / "daemon.pid"
        pf.write_text("not-a-number\n")
        assert read_pidfile(pf) is None

    def test_remove(self, tmp_path: Path) -> None:
        pf = tmp_path / "daemon.pid"
        write_pidfile(pf, 12345)
        remove_pidfile(pf)
        assert not pf.exists()

    def test_remove_missing(self, tmp_path: Path) -> None:
        pf = tmp_path / "daemon.pid"
        remove_pidfile(pf)  # should not raise


class TestPaths:
    def test_socket_path(self, tmp_path: Path) -> None:
        assert socket_path(tmp_path) == tmp_path / ".orca" / "daemon.sock"

    def test_pidfile_path(self, tmp_path: Path) -> None:
        assert pidfile_path(tmp_path) == tmp_path / ".orca" / "daemon.pid"


class TestCheckDaemonRunning:
    def test_not_running_no_pidfile(self, tmp_path: Path) -> None:
        (tmp_path / ".orca").mkdir()
        assert check_daemon_running(tmp_path) is False

    def test_not_running_stale_pid(self, tmp_path: Path) -> None:
        orca_dir = tmp_path / ".orca"
        orca_dir.mkdir()
        pf = orca_dir / "daemon.pid"
        # PID 99999999 should not exist on any system
        write_pidfile(pf, 99999999)
        assert check_daemon_running(tmp_path) is False
        # Stale pidfile should be cleaned up
        assert not pf.exists()

    def test_running(self, tmp_path: Path) -> None:
        orca_dir = tmp_path / ".orca"
        orca_dir.mkdir()
        pf = orca_dir / "daemon.pid"
        # Use our own PID, which is guaranteed alive
        write_pidfile(pf, os.getpid())
        assert check_daemon_running(tmp_path) is True


class TestCleanupStaleSocket:
    def test_removes_stale_socket(self, tmp_path: Path) -> None:
        orca_dir = tmp_path / ".orca"
        orca_dir.mkdir()
        sock = orca_dir / "daemon.sock"
        sock.touch()
        cleanup_stale_socket(tmp_path)
        assert not sock.exists()

    def test_noop_when_no_socket(self, tmp_path: Path) -> None:
        (tmp_path / ".orca").mkdir()
        cleanup_stale_socket(tmp_path)  # should not raise


class TestSendStopSignal:
    def test_returns_false_when_no_pidfile(self, tmp_path: Path) -> None:
        (tmp_path / ".orca").mkdir()
        assert send_stop_signal(tmp_path) is False

    def test_returns_false_when_stale_pid(self, tmp_path: Path) -> None:
        orca_dir = tmp_path / ".orca"
        orca_dir.mkdir()
        pf = orca_dir / "daemon.pid"
        write_pidfile(pf, 99999999)
        assert send_stop_signal(tmp_path) is False


class TestDaemonDir:
    def test_returns_path_under_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = Path("/Users/alice/work/myrepo")
        result = daemon_dir(repo)
        repo_hash = hashlib.sha1(str(repo).encode()).hexdigest()[:12]
        assert result == fake_home / ".orca" / "daemons" / repo_hash

    def test_deterministic(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = Path("/Users/alice/work/myrepo")
        assert daemon_dir(repo) == daemon_dir(repo)

    def test_different_repos_different_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        assert daemon_dir(Path("/repo/a")) != daemon_dir(Path("/repo/b"))


class TestDaemonAlreadyRunningError:
    def test_stores_pid(self) -> None:
        err = DaemonAlreadyRunningError(42)
        assert err.pid == 42
        assert "42" in str(err)
