"""Small async git utilities shared between orchestrator and snapshot code."""

from __future__ import annotations

import asyncio
from pathlib import Path


async def current_head(repo_or_worktree: Path) -> str | None:
    """Return current HEAD commit SHA, or None if no commits yet."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "HEAD",
        cwd=str(repo_or_worktree),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    return stdout.decode().strip() or None
