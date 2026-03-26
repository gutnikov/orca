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
