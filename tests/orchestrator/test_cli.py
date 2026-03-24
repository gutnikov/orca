from __future__ import annotations

from pathlib import Path

import pytest

from orca.orchestrator.runner import resolve_config_path


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
