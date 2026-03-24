from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from orca.orchestrator.runner import resolve_branch, resolve_config_path


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
    def test_explicit_branch_returned_as_is(self) -> None:
        assert resolve_branch("my-feature") == "my-feature"

    def test_none_resolves_to_current_branch(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n")
            assert resolve_branch(None) == "main"

    def test_detached_head_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="HEAD\n")
            with pytest.raises(SystemExit):
                resolve_branch(None)

    def test_empty_stdout_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="\n")
            with pytest.raises(SystemExit):
                resolve_branch(None)

    def test_nonzero_returncode_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=128, stdout="")
            with pytest.raises(SystemExit):
                resolve_branch(None)

    def test_git_failure_raises(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            with pytest.raises(SystemExit):
                resolve_branch(None)
