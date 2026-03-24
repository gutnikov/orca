from __future__ import annotations

from pathlib import Path
from typing import Any

from orca.engine.types import EventLogEntry, Issue, State


class TestSerializeStateForInsights:
    def test_serializes_all_issues(self) -> None:
        from orca.orchestrator.insights import serialize_state_for_insights

        state = State(
            issues={
                "i1": Issue(
                    fields={"title": "Root task"},
                    state="coding",
                    worker_active=True,
                    decomposed_from=None,
                    depends_on=[],
                    event_log=[EventLogEntry(timestamp="2026-01-01T00:00:00", type="created", data={})],
                    visit_counts={"coding": 1},
                    hop_count=0,
                    failure_count=0,
                ),
                "i2": Issue(
                    fields={"title": "Sub task"},
                    state="done",
                    worker_active=False,
                    decomposed_from="i1",
                    depends_on=[],
                    event_log=[],
                    visit_counts={"done": 1},
                    hop_count=1,
                    failure_count=2,
                ),
            },
            worker_queues={},
        )

        result = serialize_state_for_insights(state)

        assert "i1" in result["issues"]
        assert "i2" in result["issues"]
        assert result["issues"]["i1"]["fields"]["title"] == "Root task"
        assert result["issues"]["i1"]["state"] == "coding"
        assert result["issues"]["i1"]["worker_active"] is True
        assert result["issues"]["i2"]["failure_count"] == 2
        assert result["issues"]["i2"]["decomposed_from"] == "i1"


class TestGatherTranscripts:
    def test_reads_existing_transcripts(self, tmp_path: Path) -> None:
        from orca.orchestrator.insights import gather_transcripts

        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        (transcripts_dir / "sess-1.md").write_text("# Transcript 1\nSome content here\n" * 20)
        (transcripts_dir / "sess-2.md").write_text("# Transcript 2\nMore content\n" * 10)

        sessions: list[dict[str, Any]] = [
            {"session_id": "sess-1", "issue_id": "i1", "completed_at": "2026-01-01"},
            {"session_id": "sess-2", "issue_id": "i2", "completed_at": None},
        ]

        result = gather_transcripts(transcripts_dir, sessions, max_lines_per_transcript=200)

        assert "sess-1" in result
        assert "sess-2" in result
        assert "Transcript 1" in result["sess-1"]

    def test_skips_insights_sessions(self, tmp_path: Path) -> None:
        from orca.orchestrator.insights import gather_transcripts

        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        (transcripts_dir / "sess-insights.md").write_text("insights transcript")

        sessions = [
            {"session_id": "sess-insights", "issue_id": "__insights__", "completed_at": None},
        ]

        result = gather_transcripts(transcripts_dir, sessions, max_lines_per_transcript=200)
        assert len(result) == 0

    def test_truncates_long_transcripts(self, tmp_path: Path) -> None:
        from orca.orchestrator.insights import gather_transcripts

        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        long_content = "\n".join(f"line {i}" for i in range(500))
        (transcripts_dir / "sess-1.md").write_text(long_content)

        sessions = [{"session_id": "sess-1", "issue_id": "i1", "completed_at": None}]

        result = gather_transcripts(transcripts_dir, sessions, max_lines_per_transcript=50)
        lines = result["sess-1"].split("\n")
        assert len(lines) <= 50

    def test_global_budget_cap(self, tmp_path: Path) -> None:
        from orca.orchestrator.insights import gather_transcripts

        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        for i in range(10):
            content = "\n".join(f"line {j}" for j in range(200))
            (transcripts_dir / f"sess-{i}.md").write_text(content)

        sessions: list[dict[str, Any]] = [
            {"session_id": f"sess-{i}", "issue_id": f"i{i}", "completed_at": None} for i in range(10)
        ]

        result = gather_transcripts(transcripts_dir, sessions, max_lines_per_transcript=200, global_budget=500)
        total_lines = sum(len(v.split("\n")) for v in result.values())
        assert total_lines <= 500


class TestTruncateInsightsSoFar:
    def test_truncates_to_max_lines(self) -> None:
        from orca.orchestrator.insights import truncate_insights_so_far

        content = "\n".join(f"line {i}" for i in range(5000))
        result = truncate_insights_so_far(content, max_lines=3000)
        assert len(result.split("\n")) <= 3000

    def test_short_content_unchanged(self) -> None:
        from orca.orchestrator.insights import truncate_insights_so_far

        content = "just a few lines\nof content"
        assert truncate_insights_so_far(content, max_lines=3000) == content
