from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from orca.tui.widgets.terminal_view import TerminalView


def test_terminal_view_initial_state() -> None:
    """TerminalView starts in placeholder state with no log path."""
    view = TerminalView()
    assert view._log_path is None
    assert view._timer_handle is None
    assert view._active_tab == "session"


def test_terminal_view_show_log_file_sets_path(tmp_path: Path) -> None:
    """show_log_file sets the log path."""
    log = tmp_path / "test.log"
    log.write_text("hello")
    view = TerminalView()
    view.show_log_file(log, active=False)
    assert view._log_path == log


def test_show_log_with_result_defaults_to_result_tab(tmp_path: Path) -> None:
    """Completed (not active) with result -> result tab."""
    view = TerminalView()
    result = {"outcome": "ready", "summary": "done"}
    log = tmp_path / "test.log"
    log.write_text("hello")
    view.show_log_file(log, active=False, result=result, state_name="planning")
    assert view._active_tab == "result"
    assert view._result_data == result


def test_show_log_active_defaults_to_session(tmp_path: Path) -> None:
    """Active worker defaults to session tab."""
    view = TerminalView()
    log = tmp_path / "test.log"
    log.write_text("hello")
    with patch.object(view, "set_interval", return_value=None):
        view.show_log_file(log, active=True)
    assert view._active_tab == "session"


def test_toggle_tab(tmp_path: Path) -> None:
    """Toggle switches between session and result tabs."""
    view = TerminalView()
    result = {"outcome": "ready"}
    log = tmp_path / "test.log"
    log.write_text("hello")
    view.show_log_file(log, active=False, result=result, state_name="test")
    assert view._active_tab == "result"
    view.toggle_tab()
    assert view._active_tab == "session"
    view.toggle_tab()
    assert view._active_tab == "result"


def test_toggle_tab_no_result_does_nothing(tmp_path: Path) -> None:
    """Toggle does nothing when no result data is available."""
    view = TerminalView()
    log = tmp_path / "test.log"
    log.write_text("hello")
    with patch.object(view, "set_interval", return_value=None):
        view.show_log_file(log, active=True)
    view.toggle_tab()
    assert view._active_tab == "session"  # unchanged, no result data
