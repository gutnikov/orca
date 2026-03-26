from __future__ import annotations

import re
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

# Strip all background colors, reverse video, and near-white foregrounds
# that clash with the TUI's dark theme.
_STRIP_RE = re.compile(
    r"\x1b\["
    r"(?:"
    r"4[0-7]"  # basic bg (40-47)
    r"|48;[25];\d+(?:;\d+)*"  # 256-color/truecolor bg
    r"|49"  # default bg reset
    r"|10[0-7]"  # bright bg (100-107)
    r"|7|27"  # reverse video on/off
    r"|38;5;231"  # bright white fg (clashes on dark theme)
    r"|38;2;248;248;242"  # near-white fg from code blocks
    r"|38;2;255;255;255"  # pure white fg
    r")m"
)

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
            # Strip backgrounds, reverse video, and white foregrounds
            raw = _STRIP_RE.sub("", raw)
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
