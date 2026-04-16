from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult

from orca.tui.widgets.insights_modal import InsightsModal


class InsightsModalApp(App[None]):
    def compose(self) -> ComposeResult:
        yield InsightsModal()


class TestInsightsModal:
    @pytest.mark.asyncio
    async def test_starts_hidden(self) -> None:
        app = InsightsModalApp()
        async with app.run_test() as pilot:
            modal = app.query_one(InsightsModal)
            assert str(modal.styles.display) == "none"
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_open_and_close(self) -> None:
        app = InsightsModalApp()
        async with app.run_test() as pilot:
            modal = app.query_one(InsightsModal)
            entries: list[dict[str, Any]] = [
                {"severity": "error", "title": "Build failed", "detail": "d", "remediation": "r"},
                {"severity": "warning", "title": "Slow worker", "detail": "d", "remediation": "r"},
            ]
            modal.open(entries)
            await pilot.pause()
            assert str(modal.styles.display) != "none"
            # Access the internal content stored by Static.update()
            content = modal._static._Static__content  # type: ignore[attr-defined]
            text = str(content)
            assert "Build failed" in text
            assert "Slow worker" in text

            modal.close()
            await pilot.pause()
            assert str(modal.styles.display) == "none"

    @pytest.mark.asyncio
    async def test_empty_entries(self) -> None:
        app = InsightsModalApp()
        async with app.run_test() as pilot:
            modal = app.query_one(InsightsModal)
            modal.open([])
            await pilot.pause()
            content = modal._static._Static__content  # type: ignore[attr-defined]
            text = str(content)
            assert "No insights" in text
