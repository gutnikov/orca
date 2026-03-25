from __future__ import annotations

from rich.text import Text

from orca.tui.widgets.terminal_view import FrozenTerminal, TerminalView


def test_frozen_terminal_stores_lines() -> None:
    """FrozenTerminal is a simple container of Rich Text lines."""
    lines = [Text("line 1"), Text("line 2"), Text("line 3")]
    frozen = FrozenTerminal(lines=lines)
    assert len(frozen.lines) == 3
    assert str(frozen.lines[0]) == "line 1"


def test_terminal_view_initial_state() -> None:
    """TerminalView starts in placeholder state with no session or frozen data."""
    view = TerminalView()
    assert view._frozen is None
    assert view._tmux_session is None
    assert view._timer_handle is None
