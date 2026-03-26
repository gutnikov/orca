from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.events import Click
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

_TAB_BG = "#1e1e30"
_TAB_ACTIVE_ACCENT = "#7c6ff7"
_TAB_INACTIVE = "#555570"


class TerminalView(VerticalScroll):
    """Displays worker terminal output by reading session log files."""

    DEFAULT_CSS = """
    TerminalView {
        width: 1fr;
        padding: 1 2;
    }
    TerminalView Static {
        width: 1fr;
    }
    TerminalView #tab-bar {
        dock: top;
        height: 1;
        background: #1e1e30;
        padding: 0 1;
    }
    TerminalView #tab-session, TerminalView #tab-result {
        width: auto;
        height: 1;
        padding: 0 1;
        margin: 0 1 0 0;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="terminal-view")
        self._tab_session = Static(" Session ", id="tab-session")
        self._tab_result = Static(" Result ", id="tab-result")
        self._tab_bar = Horizontal(self._tab_session, self._tab_result, id="tab-bar")
        self._static = Static(_PLACEHOLDER)
        self._log_path: Path | None = None
        self._last_mtime: float = 0.0
        self._timer_handle: object | None = None
        self._active_tab: str = "session"
        self._result_data: dict[str, Any] | None = None
        self._result_state: str = ""
        self._result_duration: str = ""
        self._is_active_worker: bool = False

    def compose(self) -> ComposeResult:
        yield self._tab_bar
        yield self._static

    def show_log_file(
        self,
        path: Path,
        *,
        active: bool = False,
        result: dict[str, Any] | None = None,
        state_name: str = "",
        duration: str = "",
    ) -> None:
        """Display a session log file. If result provided, enable tab switching.

        For completed workers (not active) with result data, auto-show Result tab.
        """
        self._stop()
        self._log_path = path
        self._last_mtime = 0.0
        self._result_data = result
        self._result_state = state_name
        self._result_duration = duration
        self._is_active_worker = active

        # Determine default tab
        if not active and result is not None:
            self._active_tab = "result"
        else:
            self._active_tab = "session"

        self._render_tabs()

        if self._active_tab == "result":
            self._render_result()
        else:
            self._render_log()

        if active:
            self._timer_handle = self.set_interval(1.0, self._render_log)

    def show_placeholder(self) -> None:
        """Reset to placeholder state."""
        self._stop()
        self._result_data = None
        self._result_state = ""
        self._result_duration = ""
        self._is_active_worker = False
        self._active_tab = "session"
        self._static.update(_PLACEHOLDER)
        self._render_tabs()

    def toggle_tab(self) -> None:
        """Switch between session and result tabs."""
        if self._result_data is None:
            return  # no result to switch to
        if self._active_tab == "session":
            self._active_tab = "result"
            self._render_result()
        else:
            self._active_tab = "session"
            self._render_log()
        self._render_tabs()

    def _render_tabs(self) -> None:
        """Update tab bar display."""
        with contextlib.suppress(Exception):
            if self._log_path is None:
                self._tab_session.update("")
                self._tab_result.update("")
                return

            # Session tab
            if self._active_tab == "session":
                self._tab_session.update(Text(" Session ", style=f"bold underline {_TAB_ACTIVE_ACCENT}"))
            else:
                self._tab_session.update(Text(" Session ", style=_TAB_INACTIVE))

            # Result tab
            if self._result_data is not None:
                if self._active_tab == "result":
                    self._tab_result.update(Text(" Result ", style=f"bold underline {_TAB_ACTIVE_ACCENT}"))
                else:
                    self._tab_result.update(Text(" Result ", style=_TAB_INACTIVE))
            else:
                self._tab_result.update(Text(" Result ", style=f"dim {_TAB_INACTIVE}"))

    def on_click(self, event: Click) -> None:
        """Handle click on tab widgets."""
        widget = event.widget
        if (widget is self._tab_session and self._active_tab != "session") or (
            widget is self._tab_result and self._result_data is not None and self._active_tab != "result"
        ):
            self.toggle_tab()

    def _render_result(self) -> None:
        """Render result.json as formatted key/value pairs."""
        if self._result_data is None:
            return

        lines = Text()

        # Header line
        icon = "\u2713" if not self._is_active_worker else "\u25cb"
        header_parts: list[str] = []
        if self._result_state:
            header_parts.append(self._result_state)
        if self._result_duration:
            header_parts.append(f"completed in {self._result_duration}")
        header_suffix = " \u2014 ".join(header_parts) if header_parts else ""

        lines.append_text(Text(f"\n  {icon} {header_suffix}\n\n", style="bold"))

        # Key/value pairs
        max_key_len = max((len(str(k)) for k in self._result_data), default=0)
        col_width = max(max_key_len + 2, 20)

        for key, value in self._result_data.items():
            formatted_values = _format_value(value)
            for i, line in enumerate(formatted_values):
                if i == 0:
                    label = f"  {key:<{col_width}}"
                    lines.append_text(Text(label, style="bold #8888aa"))
                    lines.append_text(Text(f"{line}\n"))
                else:
                    padding = " " * (col_width + 2)
                    lines.append_text(Text(f"{padding}{line}\n"))

        with contextlib.suppress(Exception):
            self._static.update(lines)

    def _render_log(self) -> None:
        """Read log file and render to the Static widget."""
        if self._log_path is None:
            return
        # Skip if we're on the result tab (don't overwrite result with log)
        if self._active_tab == "result":
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


def _format_value(value: Any) -> list[str]:
    """Format a result value into display lines."""
    if isinstance(value, list):
        if not value:
            return ["(empty)"]
        return [str(item) for item in value]
    if isinstance(value, dict):
        if not value:
            return ["{}"]
        lines: list[str] = []
        for k, v in value.items():
            lines.append(f"{k}: {v}")
        return lines
    return [str(value)]
