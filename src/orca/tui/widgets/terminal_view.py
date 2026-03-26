from __future__ import annotations

import re
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

# Strip background colors and reverse video from ANSI output
_BG_RE = re.compile(r"\x1b\[(?:48;[25];\d+(?:;\d+)*|(?:27|7))m")

_PLACEHOLDER = "*Select a worker run to view its terminal output*"


class TerminalView(VerticalScroll):
    """Displays worker terminal output by reading session log files."""

    DEFAULT_CSS = """
    TerminalView {
        width: 1fr;
        padding: 1;
    }
    TerminalView Static {
        width: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="terminal-view")
        self._static = Static(_PLACEHOLDER)
        self._log_path: Path | None = None
        self._last_mtime: float = 0.0
        self._timer_handle: object | None = None

    def compose(self) -> ComposeResult:
        yield self._static

    def show_log_file(self, path: Path, *, active: bool = False) -> None:
        """Display a session log file. If active, poll for updates."""
        self._stop()
        self._log_path = path
        self._last_mtime = 0.0
        self._render_log()
        if active:
            self._timer_handle = self.set_interval(1.0, self._render_log)

    def show_placeholder(self) -> None:
        """Reset to placeholder state."""
        self._stop()
        self._static.update(_PLACEHOLDER)

    def _render_log(self) -> None:
        """Read log file and render to the Static widget."""
        if self._log_path is None:
            return
        try:
            if not self._log_path.exists():
                if self._last_mtime == 0.0:
                    self._static.update("*Waiting for session output...*")
                return
            mtime = self._log_path.stat().st_mtime
            if mtime == self._last_mtime:
                return  # no change
            self._last_mtime = mtime
            raw = self._log_path.read_text(errors="replace")
            if not raw:
                return
            # Strip background colors and reverse video
            raw = _BG_RE.sub("", raw)
            content = Text.from_ansi(raw)
            self._static.update(content)
            if self.max_scroll_y - self.scroll_y < 5:
                self.scroll_end(animate=False)
        except Exception:
            pass  # best-effort — next tick will retry

    def _stop(self) -> None:
        """Stop any active polling."""
        if self._timer_handle is not None:
            self._timer_handle.stop()  # type: ignore[attr-defined]
            self._timer_handle = None
        self._log_path = None
        self._last_mtime = 0.0

    def clear(self) -> None:
        self.show_placeholder()
