import asyncio
import subprocess
from pathlib import Path

import pytest

from orca.orchestrator.worktree import WorktreeError, WorktreeManager


def _run(cmd: list[str], cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


@pytest.fixture
def repo_with_worktree(tmp_path: Path) -> tuple[WorktreeManager, str, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "T"], repo)
    (repo / "a").write_text("1\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-qm", "c1"], repo)
    base_commit = _run(["git", "rev-parse", "HEAD"], repo)

    mgr = WorktreeManager(repo, "main")
    wt = asyncio.run(mgr.create(issue_id="i1", branch_name="feat", parent_branch="main"))
    (wt / "b").write_text("2\n")
    _run(["git", "add", "."], wt)
    _run(["git", "commit", "-qm", "c2"], wt)
    (wt / "c").write_text("3\n")
    _run(["git", "add", "."], wt)
    _run(["git", "commit", "-qm", "c3"], wt)

    return mgr, base_commit, wt


def test_reset_to_rewinds_and_cleans_untracked(repo_with_worktree: tuple[WorktreeManager, str, Path]) -> None:
    mgr, base_commit, wt = repo_with_worktree
    (wt / "untracked.txt").write_text("garbage")

    asyncio.run(mgr.reset_to("feat", base_commit))

    head = _run(["git", "rev-parse", "HEAD"], wt)
    assert head == base_commit
    assert not (wt / "untracked.txt").exists()
    assert not (wt / "b").exists()
    assert not (wt / "c").exists()


def test_reset_to_raises_on_unknown_commit(repo_with_worktree: tuple[WorktreeManager, str, Path]) -> None:
    mgr, _, _ = repo_with_worktree
    with pytest.raises(WorktreeError):
        asyncio.run(mgr.reset_to("feat", "deadbeefdeadbeef"))
