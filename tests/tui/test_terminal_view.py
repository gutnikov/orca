from __future__ import annotations

from pathlib import Path

from orca.tui.widgets.terminal_view import TerminalView


def test_terminal_view_initial_state() -> None:
    """TerminalView starts in placeholder state with no log path."""
    view = TerminalView()
    assert view._log_path is None
    assert view._timer_handle is None


def test_terminal_view_show_log_file_sets_path(tmp_path: Path) -> None:
    """show_log_file sets the log path."""
    log = tmp_path / "test.log"
    log.write_text("hello")
    view = TerminalView()
    view.show_log_file(log, active=False)
    assert view._log_path == log
