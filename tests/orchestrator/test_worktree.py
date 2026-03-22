from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orca.orchestrator.worktree import WorktreeManager


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)
    return tmp_path


def _current_branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class TestWorktreeManager:
    @pytest.mark.asyncio()
    async def test_create_worktree(self, git_repo: Path) -> None:
        branch = _current_branch(git_repo)
        manager = WorktreeManager(repo_root=git_repo, root_branch=branch)
        path = await manager.create(
            issue_id="issue-1",
            branch_name="my-feature",
            parent_branch=branch,
        )
        assert path == git_repo / ".orca" / "worktrees" / "my-feature"
        assert path.exists()
        assert (path / "README.md").exists()

    @pytest.mark.asyncio()
    async def test_create_child_worktree(self, git_repo: Path) -> None:
        branch = _current_branch(git_repo)
        manager = WorktreeManager(repo_root=git_repo, root_branch=branch)
        await manager.create(
            issue_id="issue-1",
            branch_name="my-feature",
            parent_branch=branch,
        )
        child_path = await manager.create(
            issue_id="issue-2",
            branch_name="my-feature/db",
            parent_branch="my-feature",
        )
        assert child_path == git_repo / ".orca" / "worktrees" / "my-feature" / "db"
        assert child_path.exists()

    @pytest.mark.asyncio()
    async def test_resolve(self, git_repo: Path) -> None:
        branch = _current_branch(git_repo)
        manager = WorktreeManager(repo_root=git_repo, root_branch=branch)
        path = manager.resolve("my-feature")
        assert path == git_repo / ".orca" / "worktrees" / "my-feature"
        assert not path.exists()

    @pytest.mark.asyncio()
    async def test_create_existing_worktree_is_idempotent(self, git_repo: Path) -> None:
        branch = _current_branch(git_repo)
        manager = WorktreeManager(repo_root=git_repo, root_branch=branch)
        path1 = await manager.create(
            issue_id="issue-1",
            branch_name="my-feature",
            parent_branch=branch,
        )
        path2 = await manager.create(
            issue_id="issue-1",
            branch_name="my-feature",
            parent_branch=branch,
        )
        assert path1 == path2
        assert path1.exists()
