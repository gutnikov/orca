from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from orca.engine import parse_config, reduce
from orca.engine.types import CreateEvent, EventLogEntry, Issue, State
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.worker import WorkerOutcome, WorkerSuccess
from orca.orchestrator.worktree import WorktreeManager


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


class _FakeWorktreeManager(WorktreeManager):
    def __init__(self, base: Path) -> None:
        super().__init__(base, "main")

    async def create(self, issue_id: str, branch_name: str, parent_branch: str) -> Path:
        p = self.resolve(branch_name)
        p.mkdir(parents=True, exist_ok=True)
        return p


SIMPLE_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: Title
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/todo.md
      result_format:
        outcome:
          type: enum
          values: [done]
          description: Decision
    on:
      done: complete
  complete:
    terminal: true
initial: todo
"""


class _MockWorker:
    async def execute(
        self,
        effect: Any,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: Any = None,
        log_path: Path | None = None,
    ) -> WorkerOutcome:
        return WorkerSuccess(result={"outcome": "done"})


class TestInsightsIntegration:
    @pytest.mark.asyncio()
    async def test_insights_worker_invoked_during_run(self, tmp_path: Path) -> None:
        """Full flow: orchestrator with insights_worker calls execute_raw."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})

        _id_counter = 0

        def _gen_id() -> str:
            nonlocal _id_counter
            _id_counter += 1
            return f"issue-{_id_counter}"

        def _now() -> str:
            return "2026-01-01T00:00:00Z"

        create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp=_now())
        state, initial_effects = reduce(config, state, create_event, _gen_id, _now)

        persistence = Persistence(tmp_path, "main")
        persistence.save(state)
        branches = BranchMap(tmp_path, "main")

        mock_insights = MagicMock()
        mock_insights.execute_raw = AsyncMock(return_value=WorkerSuccess(result={}))

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=persistence,
            branches=branches,
            workers={"claude-code": _MockWorker()},
            generate_id=_gen_id,
            now=_now,
            worktree_mgr=_FakeWorktreeManager(tmp_path),
            repo_root=tmp_path,
            insights_worker=mock_insights,
            insights_interval=0.05,
        )

        await orchestrator.run("issue-1", initial_effects)

        # Root issue should reach terminal state
        assert orchestrator.state.issues["issue-1"].state == "complete"
        # Insights worker should have been called (at least the final run)
        assert mock_insights.execute_raw.call_count >= 1
