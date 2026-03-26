from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orca.orchestrator.runner import _git_branch_exists, _git_create_branch
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


class TestConcurrentRunIsolation:
    @pytest.mark.asyncio()
    async def test_two_runs_create_isolated_worktrees(self, git_repo: Path) -> None:
        base = _current_branch(git_repo)

        # Simulate two runs creating branches and worktrees
        await _git_create_branch("feature-auth", base, git_repo)
        await _git_create_branch("feature-billing", base, git_repo)

        mgr_a = WorktreeManager(repo_root=git_repo, root_branch="feature-auth")
        mgr_b = WorktreeManager(repo_root=git_repo, root_branch="feature-billing")

        path_a = await mgr_a.create(issue_id="root-a", branch_name="feature-auth", parent_branch=base)
        path_b = await mgr_b.create(issue_id="root-b", branch_name="feature-billing", parent_branch=base)

        # Worktrees are isolated
        assert path_a != path_b
        assert path_a.exists()
        assert path_b.exists()

        # State directories would be isolated
        state_a = git_repo / ".orca" / "runs" / "feature-auth"
        state_b = git_repo / ".orca" / "runs" / "feature-billing"
        assert state_a != state_b

    @pytest.mark.asyncio()
    async def test_branch_created_from_base_ref(self, git_repo: Path) -> None:
        base = _current_branch(git_repo)

        # Get the commit SHA of the base
        result = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", base],
            check=True,
            capture_output=True,
            text=True,
        )
        base_sha = result.stdout.strip()

        await _git_create_branch("feature-auth", base, git_repo)

        # Verify the new branch points to the same commit
        result = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "feature-auth"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == base_sha

    @pytest.mark.asyncio()
    async def test_resume_skips_branch_creation(self, git_repo: Path) -> None:
        base = _current_branch(git_repo)
        await _git_create_branch("feature-auth", base, git_repo)

        # Branch already exists — _git_branch_exists should return True
        assert await _git_branch_exists("feature-auth", git_repo)
