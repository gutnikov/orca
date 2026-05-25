"""HTTP endpoint tests for inline comments + comment threads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from orca.daemon.http_api import create_app
from orca.daemon.manager import RunInfo, RunManager, RunStatus
from orca.engine import parse_config
from orca.engine.types import Issue, State
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.worker import WorkerOutcome
from orca.orchestrator.worktree import WorktreeManager


class _FakeWorktreeManager(WorktreeManager):
    """WorktreeManager substitute that does not touch git."""

    def __init__(self, base: Path) -> None:
        super().__init__(base, "main")

    async def create(self, issue_id: str, branch_name: str, parent_branch: str) -> Path:
        p = self.resolve(branch_name)
        p.mkdir(parents=True, exist_ok=True)
        return p


class _NoopWorker:
    async def execute(self, *args: Any, **kwargs: Any) -> WorkerOutcome:  # pragma: no cover
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


RUN_ID = "main:default"
ISSUE_ID = "issue-1"


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
    state = State(issues={ISSUE_ID: issue}, worker_queues={})
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
        worktree_mgr=_FakeWorktreeManager(tmp_path),
    )


@pytest.fixture()
def client_with_run(tmp_path: Path) -> TestClient:
    """A TestClient bound to a manager that already has one run with one issue."""
    manager = RunManager(tmp_path)
    orchestrator = _make_orchestrator(tmp_path)
    run_info = RunInfo(
        run_id=RUN_ID,
        branch="main",
        workflow="default",
        status=RunStatus.RUNNING,
        issue_count=1,
        created_at=_now(),
        config=orchestrator._config,
        orchestrator=orchestrator,
    )
    manager._runs[RUN_ID] = run_info
    app = create_app(manager)
    return TestClient(app)


# ---------------------------------------------------------------------------- #
# PUT /comments/{comment_id} — create / update                                 #
# ---------------------------------------------------------------------------- #


def test_put_creates_inline_comment_and_get_returns_it(client_with_run: TestClient) -> None:
    r = client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "src/foo.ts", "line": 42, "body": "needs work"},
    )
    assert r.status_code == 200

    g = client_with_run.get(f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments")
    assert g.status_code == 200
    payload = g.json()
    assert "comments" in payload
    assert len(payload["comments"]) == 1
    comment = payload["comments"][0]
    assert comment["id"] == "c1"
    assert comment["file"] == "src/foo.ts"
    assert comment["line"] == 42
    assert comment["body"] == "needs work"
    assert comment["thread"] is None


def test_put_same_comment_id_updates_in_place(client_with_run: TestClient) -> None:
    client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "src/foo.ts", "line": 10, "body": "v1"},
    )
    r = client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "src/foo.ts", "line": 10, "body": "v2 edited"},
    )
    assert r.status_code == 200

    g = client_with_run.get(f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments")
    comments = g.json()["comments"]
    assert len(comments) == 1
    assert comments[0]["body"] == "v2 edited"


def test_put_accepts_null_line(client_with_run: TestClient) -> None:
    r = client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "src/foo.ts", "line": None, "body": "file-level"},
    )
    assert r.status_code == 200
    g = client_with_run.get(f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments")
    assert g.json()["comments"][0]["line"] is None


# ---------------------------------------------------------------------------- #
# DELETE /comments/{comment_id}                                                #
# ---------------------------------------------------------------------------- #


def test_delete_removes_comment_and_thread(client_with_run: TestClient) -> None:
    client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "src/foo.ts", "line": 1, "body": "hi"},
    )
    client_with_run.post(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1/messages",
        json={"role": "agent", "body": "reply"},
    )

    r = client_with_run.delete(f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1")
    assert r.status_code == 200

    g = client_with_run.get(f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments")
    assert g.json()["comments"] == []


# ---------------------------------------------------------------------------- #
# POST /comments/{comment_id}/messages                                         #
# ---------------------------------------------------------------------------- #


def test_post_message_creates_thread_lazily(client_with_run: TestClient) -> None:
    client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "src/foo.ts", "line": 1, "body": "please clarify"},
    )
    r = client_with_run.post(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1/messages",
        json={"role": "agent", "body": "hi"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert "message_id" in payload
    assert isinstance(payload["message_id"], str)
    assert payload["message_id"]

    g = client_with_run.get(f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments")
    thread = g.json()["comments"][0]["thread"]
    assert thread is not None
    assert len(thread["messages"]) == 1
    assert thread["messages"][0]["role"] == "agent"
    assert thread["messages"][0]["body"] == "hi"
    assert thread["messages"][0]["id"] == payload["message_id"]
    assert thread["agent_last_reviewed_at"] is not None


# ---------------------------------------------------------------------------- #
# POST /comments/{comment_id}/skip                                             #
# ---------------------------------------------------------------------------- #


def test_post_skip_creates_empty_thread_and_bumps_reviewed_at(
    client_with_run: TestClient,
) -> None:
    client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "src/foo.ts", "line": 1, "body": "trivial"},
    )
    r = client_with_run.post(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1/skip",
        json={"reason": "not actionable"},
    )
    assert r.status_code == 200

    g = client_with_run.get(f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments")
    thread = g.json()["comments"][0]["thread"]
    assert thread is not None
    assert thread["messages"] == []
    assert thread["agent_last_reviewed_at"] is not None


# ---------------------------------------------------------------------------- #
# 404 cases                                                                    #
# ---------------------------------------------------------------------------- #


def test_put_404_on_unknown_run(client_with_run: TestClient) -> None:
    r = client_with_run.put(
        "/api/runs/none:none/issues/x/comments/c1",
        json={"file": "f", "line": 1, "body": "b"},
    )
    assert r.status_code == 404
    assert "error" in r.json()


def test_put_404_on_unknown_issue(client_with_run: TestClient) -> None:
    r = client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/nope/comments/c1",
        json={"file": "f", "line": 1, "body": "b"},
    )
    assert r.status_code == 404


def test_get_404_on_unknown_run(client_with_run: TestClient) -> None:
    r = client_with_run.get("/api/runs/none:none/issues/x/comments")
    assert r.status_code == 404


def test_delete_404_on_unknown_run(client_with_run: TestClient) -> None:
    r = client_with_run.delete("/api/runs/none:none/issues/x/comments/c1")
    assert r.status_code == 404


def test_post_message_404_on_unknown_comment(client_with_run: TestClient) -> None:
    # Run + issue exist, but the comment_id was never PUT.
    r = client_with_run.post(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/missing/messages",
        json={"role": "agent", "body": "b"},
    )
    assert r.status_code == 404
    assert "not found" in r.json().get("error", "").lower()


def test_post_skip_404_on_unknown_comment(client_with_run: TestClient) -> None:
    r = client_with_run.post(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/missing/skip",
        json={"reason": "x"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------- #
# 400 validation cases                                                         #
# ---------------------------------------------------------------------------- #


def test_put_400_missing_file(client_with_run: TestClient) -> None:
    r = client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"line": 1, "body": "b"},
    )
    assert r.status_code == 400


def test_put_400_missing_body(client_with_run: TestClient) -> None:
    r = client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "f", "line": 1},
    )
    assert r.status_code == 400


def test_put_400_invalid_json(client_with_run: TestClient) -> None:
    r = client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_message_400_on_invalid_role(client_with_run: TestClient) -> None:
    client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "f", "line": 1, "body": "b"},
    )
    r = client_with_run.post(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1/messages",
        json={"role": "reviewer", "body": "hi"},
    )
    assert r.status_code == 400
    assert "role" in r.json().get("error", "").lower()


def test_post_message_400_on_missing_body(client_with_run: TestClient) -> None:
    client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "f", "line": 1, "body": "b"},
    )
    r = client_with_run.post(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1/messages",
        json={"role": "agent"},
    )
    assert r.status_code == 400


def test_post_message_400_on_empty_body(client_with_run: TestClient) -> None:
    client_with_run.put(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1",
        json={"file": "f", "line": 1, "body": "b"},
    )
    r = client_with_run.post(
        f"/api/runs/{RUN_ID}/issues/{ISSUE_ID}/comments/c1/messages",
        json={"role": "agent", "body": "   "},
    )
    assert r.status_code == 400
