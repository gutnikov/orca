"""Small helper for reading file contents at a specific git ref."""

from __future__ import annotations

import asyncio
from pathlib import Path


async def git_show_file(worktree: Path, ref: str, path: str) -> str:
    """Return file contents at <ref>:<path>, or empty string on failure."""
    return await _run(worktree, ref, path)


async def _run(worktree: Path, ref: str, path: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "show",
        f"{ref}:{path}",
        cwd=str(worktree),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return ""
    return stdout.decode("utf-8", errors="replace")
