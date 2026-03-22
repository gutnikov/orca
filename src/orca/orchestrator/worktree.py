from __future__ import annotations

import asyncio
from pathlib import Path


class WorktreeError(Exception):
    pass


class WorktreeManager:
    def __init__(self, repo_root: Path, root_branch: str) -> None:
        self.repo_root = repo_root
        self.root_branch = root_branch

    async def create(
        self,
        issue_id: str,
        branch_name: str,
        parent_branch: str,
    ) -> Path:
        """Create a git worktree for an issue. Returns the worktree path."""
        worktree_path = self.resolve(branch_name)
        if worktree_path.exists():
            return worktree_path

        # Git branch refs cannot be hierarchical when a parent ref already exists
        # (e.g. 'my-feature/db' fails when 'my-feature' branch exists).
        # Use a flat git branch name by replacing '/' with '-'.
        git_branch_name = branch_name.replace("/", "-")

        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "add",
            "-b",
            git_branch_name,
            str(worktree_path),
            parent_branch,
            cwd=str(self.repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"Failed to create worktree for {branch_name}: {stderr.decode()}"
            raise WorktreeError(msg)
        return worktree_path

    def resolve(self, branch_name: str) -> Path:
        """Get the worktree path for a branch name."""
        return self.repo_root / ".orca" / "worktrees" / branch_name
