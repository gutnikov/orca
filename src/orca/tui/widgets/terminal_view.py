from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Resize
from textual.widgets import Static

from orca.orchestrator.pty_session import TmuxSession

_PLACEHOLDER = "*Select a worker run to view its terminal output*"


@dataclass(frozen=True)
class FrozenTerminal:
    """Captured terminal state from a completed worker."""

    lines: list[Text]


class TerminalView(VerticalScroll):
    """Displays live tmux session output or frozen terminal snapshots."""

    DEFAULT_CSS = """
    TerminalView {
        width: 1fr;
        padding: 0;
    }
    TerminalView Static {
        width: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="terminal-view")
        self._static = Static(_PLACEHOLDER)
        self._tmux_session: TmuxSession | None = None
        self._frozen: FrozenTerminal | None = None
        self._timer_handle: object | None = None

    def compose(self) -> ComposeResult:
        yield self._static

    def show_live(self, session: TmuxSession) -> None:
        """Attach to a live TmuxSession and start polling its pane content."""
        self._stop()
        self._tmux_session = session
        self._frozen = None
        self._static.update("*Connecting to live session...*")
        self._timer_handle = self.set_interval(1.0, self._render_screen)

    def show_frozen(self, frozen: FrozenTerminal) -> None:
        """Display a frozen terminal snapshot."""
        self._stop()
        self._frozen = frozen
        self._tmux_session = None
        content = Text("\n").join(frozen.lines) if frozen.lines else Text(_PLACEHOLDER)
        self._static.update(content)

    def show_placeholder(self) -> None:
        """Reset to placeholder state."""
        self._stop()
        self._static.update(_PLACEHOLDER)

    def _render_screen(self) -> None:
        """Poll tmux capture-pane and render to the Static widget."""
        if self._tmux_session is None:
            return
        try:
            content = self._tmux_session.capture_rich()
            if content:
                self._static.update(content)
                if self.max_scroll_y - self.scroll_y < 5:
                    self.scroll_end(animate=False)
        except Exception:
            pass  # Swallow render errors — next tick will retry

    def _stop(self) -> None:
        """Stop any active rendering."""
        if self._timer_handle is not None:
            self._timer_handle.stop()  # type: ignore[attr-defined]
            self._timer_handle = None
        self._tmux_session = None
        self._frozen = None

    def on_resize(self, event: Resize) -> None:
        """Propagate resize to live tmux session."""
        if self._tmux_session is not None:
            width = self.content_size.width
            height = self.content_size.height
            if width > 0 and height > 0:
                self._tmux_session.resize(width, height)

    def clear(self) -> None:
        self.show_placeholder()
