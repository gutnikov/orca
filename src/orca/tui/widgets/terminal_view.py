from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Resize
from textual.widgets import Static

from orca.orchestrator.pty_session import PtySession

_PLACEHOLDER = "*Select a worker run to view its terminal output*"


@dataclass(frozen=True)
class FrozenTerminal:
    """Captured terminal state from a completed worker."""

    lines: list[Text]


class TerminalView(VerticalScroll):
    """Displays live pty output or frozen terminal snapshots."""

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
        self._pty_session: PtySession | None = None
        self._frozen: FrozenTerminal | None = None
        self._timer_handle: object | None = None

    def compose(self) -> ComposeResult:
        yield self._static

    def show_live(self, session: PtySession) -> None:
        """Attach to a live PtySession and start rendering."""
        self._stop()
        self._pty_session = session
        self._frozen = None
        self._render_screen()
        self._timer_handle = self.set_interval(1 / 20, self._render_screen)  # 50ms

    def show_frozen(self, frozen: FrozenTerminal) -> None:
        """Display a frozen terminal snapshot."""
        self._stop()
        self._frozen = frozen
        self._pty_session = None
        content = Text("\n").join(frozen.lines) if frozen.lines else Text(_PLACEHOLDER)
        self._static.update(content)

    def show_placeholder(self) -> None:
        """Reset to placeholder state."""
        self._stop()
        self._static.update(_PLACEHOLDER)

    def _render_screen(self) -> None:
        """Render current pyte screen state to the Static widget."""
        if self._pty_session is None:
            return
        screen = self._pty_session.screen
        # Take a shallow copy of buffer rows to avoid RuntimeError if
        # the orchestrator thread mutates the buffer during iteration.
        rows_copy = {row: dict(screen.buffer[row]) for row in range(screen.lines)}
        lines: list[Text] = []
        for row in range(screen.lines):
            lines.append(PtySession.pyte_line_to_rich(rows_copy[row], screen.columns))
        content = Text("\n").join(lines)
        self._static.update(content)
        if self.max_scroll_y - self.scroll_y < 5:
            self.scroll_end(animate=False)

    def _stop(self) -> None:
        """Stop any active rendering."""
        if self._timer_handle is not None:
            self._timer_handle.stop()  # type: ignore[attr-defined]
            self._timer_handle = None
        self._pty_session = None
        self._frozen = None

    def on_resize(self, event: Resize) -> None:
        """Propagate resize to live pty session."""
        if self._pty_session is not None:
            width = self.content_size.width
            height = self.content_size.height
            if width > 0 and height > 0:
                self._pty_session.resize(width, height)

    def clear(self) -> None:
        self.show_placeholder()
