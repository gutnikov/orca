"""Orchestrator direct-API tests for inline-comment + comment-thread methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orca.engine import parse_config
from orca.engine.types import Issue, State
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.worker import WorkerOutcome
from orca.orchestrator.worktree import WorktreeManager


class FakeWorktreeManager(WorktreeManager):
    """WorktreeManager substitute that does not touch git."""

    def __init__(self, base: Path) -> None:
        super().__init__(base, "main")

    async def create(self, issue_id: str, branch_name: str, parent_branch: str) -> Path:
        p = self.resolve(branch_name)
        p.mkdir(parents=True, exist_ok=True)
        return p


class _NoopWorker:
    async def execute(self, *args: Any, **kwargs: Any) -> WorkerOutcome:  # pragma: no cover - unused
        raise AssertionError("worker should not run in these tests")


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
          values: [complete]
          description: Decision
    on:
      complete: done
initial: todo
"""


def _now() -> str:
    return "2026-05-25T10:00:00+00:00"


def _id_factory() -> Any:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"id-{n}"

    return gen


def _make_orchestrator(tmp_path: Path) -> Orchestrator:
    """Build an orchestrator with a single issue already present."""
    config = parse_config(SIMPLE_CONFIG)
    issue = Issue(
        type="issue",
        fields={"title": "Test"},
        state="todo",
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
    )
    state = State(issues={"issue-1": issue}, worker_queues={})
    persistence = Persistence(tmp_path, "main")
    persistence.save(state)
    branches = BranchMap(tmp_path, "main")
    return Orchestrator(
        config=config,
        state=state,
        root_branch="main",
        persistence=persistence,
        branches=branches,
        workers={"claude-code": _NoopWorker()},
        generate_id=_id_factory(),
        now=_now,
        worktree_mgr=FakeWorktreeManager(tmp_path),
    )


def test_orchestrator_save_inline_comment_round_trip(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    orch.save_inline_comment(
        issue_id="issue-1",
        comment_id="c1",
        file="src/foo.ts",
        line=42,
        body="needs work",
    )
    rows = orch.list_inline_comments_with_threads("issue-1")
    assert len(rows) == 1
    assert rows[0]["id"] == "c1"
    assert rows[0]["file"] == "src/foo.ts"
    assert rows[0]["line"] == 42
    assert rows[0]["body"] == "needs work"
    assert rows[0]["thread"] is None


def test_orchestrator_save_inline_comment_updates_in_place(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    orch.save_inline_comment(
        issue_id="issue-1",
        comment_id="c1",
        file="src/foo.ts",
        line=10,
        body="v1",
    )
    orch.save_inline_comment(
        issue_id="issue-1",
        comment_id="c1",
        file="src/foo.ts",
        line=10,
        body="v2 edited",
    )
    rows = orch.list_inline_comments_with_threads("issue-1")
    assert len(rows) == 1
    assert rows[0]["body"] == "v2 edited"


def test_orchestrator_delete_cascades_thread(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    orch.save_inline_comment(
        issue_id="issue-1",
        comment_id="c1",
        file="src/foo.ts",
        line=1,
        body="hi",
    )
    orch.add_thread_message(issue_id="issue-1", comment_id="c1", role="agent", body="reply")
    orch.delete_inline_comment(issue_id="issue-1", comment_id="c1")
    rows = orch.list_inline_comments_with_threads("issue-1")
    assert rows == []
    # Underlying state has no orphan thread either.
    assert orch.state.issues["issue-1"].comment_threads == []


def test_orchestrator_add_thread_message_creates_thread_lazily(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    orch.save_inline_comment(
        issue_id="issue-1",
        comment_id="c1",
        file="src/foo.ts",
        line=1,
        body="please clarify",
    )
    msg_id = orch.add_thread_message(issue_id="issue-1", comment_id="c1", role="agent", body="hi")
    assert msg_id  # non-empty
    rows = orch.list_inline_comments_with_threads("issue-1")
    assert len(rows) == 1
    thread = rows[0]["thread"]
    assert thread is not None
    assert len(thread["messages"]) == 1
    msg = thread["messages"][0]
    assert msg["role"] == "agent"
    assert msg["body"] == "hi"
    assert msg["id"] == msg_id
    assert thread["agent_last_reviewed_at"] is not None


def test_orchestrator_skip_comment_creates_empty_thread_and_bumps_reviewed_at(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(tmp_path)
    orch.save_inline_comment(
        issue_id="issue-1",
        comment_id="c1",
        file="src/foo.ts",
        line=1,
        body="trivial",
    )
    orch.skip_comment(issue_id="issue-1", comment_id="c1", reason="not actionable")
    rows = orch.list_inline_comments_with_threads("issue-1")
    assert len(rows) == 1
    thread = rows[0]["thread"]
    assert thread is not None
    assert thread["messages"] == []
    assert thread["agent_last_reviewed_at"] is not None


def test_orchestrator_save_inline_comment_unknown_issue_raises(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    with pytest.raises(ValueError, match="Issue 'nope' not found"):
        orch.save_inline_comment(issue_id="nope", comment_id="c1", file="f", line=1, body="b")


def test_orchestrator_add_thread_message_unknown_comment_raises(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    with pytest.raises(ValueError, match="Comment 'missing' not found"):
        orch.add_thread_message(issue_id="issue-1", comment_id="missing", role="agent", body="b")


def test_orchestrator_add_thread_message_invalid_role_raises(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    orch.save_inline_comment(issue_id="issue-1", comment_id="c1", file="f", line=1, body="b")
    with pytest.raises(ValueError, match="Invalid role"):
        orch.add_thread_message(issue_id="issue-1", comment_id="c1", role="bot", body="hi")
