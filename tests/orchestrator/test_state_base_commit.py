import asyncio
import subprocess
from pathlib import Path

from orca.orchestrator.worktree_helpers import current_head


def _run(cmd: list[str], cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def test_current_head_returns_commit_sha(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "T"], repo)
    (repo / "x").write_text("y")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-qm", "c1"], repo)
    expected = _run(["git", "rev-parse", "HEAD"], repo)

    actual = asyncio.run(current_head(repo))
    assert actual == expected


def test_current_head_returns_none_when_no_commits(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo)
    actual = asyncio.run(current_head(repo))
    assert actual is None
