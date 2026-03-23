from __future__ import annotations

import time
from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from orca.engine.types import Issue, State
from orca.tui.widgets.issue_detail import IssueDetail


def _make_issue(title: str = "Test", description: str = "Some description") -> Issue:
    return Issue(
        fields={"title": title, "description": description},
        state="triage",
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
    )


class IssueDetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield IssueDetail()


class TestIssueDetail:
    @pytest.mark.asyncio
    async def test_shows_issue_content(self) -> None:
        app = IssueDetailApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            state = State(
                issues={"id-1": _make_issue("My Title", "My **bold** text")},
                worker_queues={},
            )
            detail.show_issue("id-1", state)
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_clears_when_issue_not_in_state(self) -> None:
        app = IssueDetailApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            state = State(issues={}, worker_queues={})
            detail.show_issue("nonexistent", state)
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_shows_transcript(self, tmp_path: Path) -> None:
        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        (transcripts_dir / "session-1.md").write_text("# Transcript\n\nHello world")

        class TranscriptApp(App[None]):
            def compose(self) -> ComposeResult:
                yield IssueDetail(transcripts_dir=transcripts_dir)

        app = TranscriptApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            detail.show_transcript("session-1")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_refresh_transcript_detects_change(self, tmp_path: Path) -> None:
        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        md_path = transcripts_dir / "session-r.md"
        md_path.write_text("# Initial\n\nFirst content\n")

        class RefreshApp(App[None]):
            def compose(self) -> ComposeResult:
                yield IssueDetail(transcripts_dir=transcripts_dir)

        app = RefreshApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            detail.show_transcript("session-r")
            await pilot.pause()
            mtime_before = detail._transcript_mtime
            assert mtime_before > 0
            # Modify the file (sleep ensures mtime changes)
            time.sleep(0.05)
            md_path.write_text("# Initial\n\nFirst content\n\nSecond content\n")
            detail.refresh_transcript()
            await pilot.pause()
            # Verify mtime was updated (proving the change was detected)
            assert detail._transcript_mtime > mtime_before
