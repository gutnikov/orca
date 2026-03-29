from __future__ import annotations

import contextlib
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from orca.tui.messages import InsightEntrySelected

_SEVERITY_ICONS = {
    "error": ("● ", "bold red"),
    "warning": ("⚠ ", "bold yellow"),
    "summary": ("◆ ", "bold cyan"),
    "info": ("ℹ ", "dim"),
}


class InsightsModal(Widget):
    """Modal overlay displaying insight entries."""

    DEFAULT_CSS = """
    InsightsModal {
        display: none;
        dock: bottom;
        width: 100%;
        height: 60%;
        background: #252540;
        border-top: solid #38b6cc;
        padding: 1 2;
        layer: overlay;
        layout: vertical;
    }
    InsightsModal Static {
        width: 1fr;
    }
    InsightsModal #insights-header {
        height: 1;
        color: #38b6cc;
        text-style: bold;
    }
    InsightsModal #insights-footer {
        dock: bottom;
        height: 1;
        color: #555555;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="insights-modal")
        self._header = Static("◆ Insights", id="insights-header")
        self._static = Static("")
        self._footer = Static("j/k navigate • Enter view detail • Esc close", id="insights-footer")
        self._entries: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._static
        yield self._footer

    def open(self, entries: list[dict[str, Any]]) -> None:
        """Show the modal with the given insight entries."""
        self._entries = entries
        self.styles.display = "block"
        self._render_entries()
        self.focus()

    def close(self) -> None:
        """Hide the modal."""
        self.styles.display = "none"

    @property
    def is_open(self) -> bool:
        return str(self.styles.display) != "none"

    def _render_entries(self) -> None:
        if not self._entries:
            self._static.update("*No insights yet*")
            return

        lines = Text()
        for i, entry in enumerate(self._entries):
            sev = str(entry.get("severity", "info"))
            title = str(entry.get("title", "Untitled"))
            detail = str(entry.get("detail", ""))
            icon, style = _SEVERITY_ICONS.get(sev, ("ℹ ", "dim"))
            lines.append(icon, style=style)
            lines.append(f"{title}\n", style="bold")
            if detail:
                lines.append(f"  {detail}\n", style="dim")
            if i < len(self._entries) - 1:
                lines.append("\n")

        with contextlib.suppress(Exception):
            self._static.update(lines)

    def select_entry(self, index: int) -> None:
        """Post an InsightEntrySelected message for the entry at the given index."""
        if 0 <= index < len(self._entries):
            e = self._entries[index]
            self.post_message(
                InsightEntrySelected(
                    title=str(e.get("title", "")),
                    detail=str(e.get("detail", "")),
                    remediation=str(e.get("remediation", "")),
                    severity=str(e.get("severity", "info")),
                )
            )
