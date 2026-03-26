from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from orca.orchestrator.runner import _git_create_branch, resolve_base_ref, resolve_branch, resolve_config_path


class TestResolveConfigPath:
    def test_default_returns_orca_yml(self, tmp_path: Path) -> None:
        (tmp_path / "orca.yml").write_text("initial: todo")
        assert resolve_config_path(tmp_path, None) == tmp_path / "orca.yml"

    def test_workflow_shorthand(self, tmp_path: Path) -> None:
        (tmp_path / "orca.develop.yml").write_text("initial: todo")
        assert resolve_config_path(tmp_path, "develop") == tmp_path / "orca.develop.yml"

    def test_missing_default_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            resolve_config_path(tmp_path, None)

    def test_missing_workflow_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            resolve_config_path(tmp_path, "develop")

    def test_error_lists_available_files(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "orca.yml").write_text("initial: todo")
        (tmp_path / "orca.test.yml").write_text("initial: todo")
        with pytest.raises(SystemExit):
            resolve_config_path(tmp_path, "develop")
        captured = capsys.readouterr()
        assert "orca.yml" in captured.err
        assert "orca.test.yml" in captured.err


class TestResolveBranch:
    def test_resolves_to_current_branch(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n")
            assert resolve_branch() == "main"

    def test_detached_head_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="HEAD\n")
            with pytest.raises(SystemExit):
                resolve_branch()

    def test_empty_stdout_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="\n")
            with pytest.raises(SystemExit):
                resolve_branch()

    def test_nonzero_returncode_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=128, stdout="")
            with pytest.raises(SystemExit):
                resolve_branch()

    def test_git_failure_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            with pytest.raises(SystemExit):
                resolve_branch()


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


class TestResolveBaseRef:
    def test_cli_takes_precedence(self) -> None:
        assert resolve_base_ref(cli_base="origin/v2", config_base="origin/develop") == "origin/v2"

    def test_config_used_when_no_cli(self) -> None:
        assert resolve_base_ref(cli_base=None, config_base="origin/develop") == "origin/develop"

    def test_default_when_neither(self) -> None:
        assert resolve_base_ref(cli_base=None, config_base="origin/main") == "origin/main"


class TestGitCreateBranch:
    @pytest.mark.asyncio()
    async def test_creates_branch_from_base(self, git_repo: Path) -> None:
        await _git_create_branch("new-feature", _current_branch(git_repo), git_repo)
        result = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "--verify", "new-feature"],
            capture_output=True,
        )
        assert result.returncode == 0

    @pytest.mark.asyncio()
    async def test_invalid_base_raises(self, git_repo: Path) -> None:
        with pytest.raises(RuntimeError, match="Failed to create branch"):
            await _git_create_branch("new-feature", "nonexistent-ref", git_repo)
