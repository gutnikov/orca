from __future__ import annotations

from pathlib import Path

import pytest

from orca.orchestrator.runner import parse_task_file, resolve_config_path


class TestParseTaskFile:
    def test_parse_title_and_description(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("Implement auth\nThis feature should support OAuth2\nand JWT tokens.")
        fields = parse_task_file(task)
        assert fields == {
            "title": "Implement auth",
            "description": "This feature should support OAuth2\nand JWT tokens.",
        }

    def test_title_only(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("Simple fix")
        fields = parse_task_file(task)
        assert fields == {"title": "Simple fix", "description": ""}

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("  Title with spaces  \n  Description  ")
        fields = parse_task_file(task)
        assert fields == {"title": "Title with spaces", "description": "Description"}

    def test_parse_yaml_fields(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text(
            "title: ai-team\n"
            "description: AI team features\n"
            "screen_paths:\n"
            "  - src/screens/ai-team/\n"
            "  - src/modules/AiTeam/\n"
        )
        fields = parse_task_file(task)
        assert fields == {
            "title": "ai-team",
            "description": "AI team features",
            "screen_paths": ["src/screens/ai-team/", "src/modules/AiTeam/"],
        }

    def test_parse_yaml_title_only(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("title: Simple fix\n")
        fields = parse_task_file(task)
        assert fields == {"title": "Simple fix"}

    def test_parse_yaml_with_frontmatter_delimiters(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("---\ntitle: ai-team\ndescription: AI team features\n---\n")
        fields = parse_task_file(task)
        assert fields == {"title": "ai-team", "description": "AI team features"}

    def test_plain_text_with_yaml_breaking_chars(self, tmp_path: Path) -> None:
        """Plain prose with `{`/`:` patterns must hit the plain-text fallback, not ScannerError."""
        task = tmp_path / "task.md"
        task.write_text("Fix the parser: handle {braces: everywhere\nMore description here.\n")
        fields = parse_task_file(task)
        assert fields == {
            "title": "Fix the parser: handle {braces: everywhere",
            "description": "More description here.",
        }

    def test_frontmatter_trailing_content_becomes_description(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("---\ntitle: My task\n---\nExtra body line one.\nLine two.\n")
        fields = parse_task_file(task)
        assert fields == {"title": "My task", "description": "Extra body line one.\nLine two."}

    def test_frontmatter_trailing_content_appended_to_description(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("---\ntitle: My task\ndescription: Base desc\n---\nTrailing notes.\n")
        fields = parse_task_file(task)
        assert fields == {"title": "My task", "description": "Base desc\n\nTrailing notes."}


class TestResolveConfigPath:
    def test_default_config(self, tmp_path: Path) -> None:
        """No workflow arg -> .orca/default.yml."""
        orca_dir = tmp_path / ".orca"
        orca_dir.mkdir()
        config = orca_dir / "default.yml"
        config.write_text("states: {}")
        result = resolve_config_path(tmp_path, None)
        assert result == config

    def test_named_workflow(self, tmp_path: Path) -> None:
        """Shorthand 'develop' -> .orca/develop.yml."""
        orca_dir = tmp_path / ".orca"
        orca_dir.mkdir()
        config = orca_dir / "develop.yml"
        config.write_text("states: {}")
        result = resolve_config_path(tmp_path, "develop")
        assert result == config

    def test_absolute_path_passthrough(self, tmp_path: Path) -> None:
        """Absolute path resolves directly (external flow)."""
        flow = tmp_path / "flows" / "my-flow.yml"
        flow.parent.mkdir()
        flow.write_text("states: {}")
        result = resolve_config_path(tmp_path, str(flow))
        assert result == flow

    def test_relative_path_passthrough(self, tmp_path: Path) -> None:
        """Relative path with / resolves against repo root."""
        flow = tmp_path / "flows" / "my-flow.yml"
        flow.parent.mkdir()
        flow.write_text("states: {}")
        result = resolve_config_path(tmp_path, "flows/my-flow.yml")
        assert result == flow.resolve()

    def test_tilde_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """~ paths expand to home directory."""
        flow = tmp_path / "my-flow.yml"
        flow.write_text("states: {}")
        monkeypatch.setenv("HOME", str(tmp_path))
        result = resolve_config_path(tmp_path, "~/my-flow.yml")
        assert result == flow.resolve()

    def test_missing_raises(self, tmp_path: Path) -> None:
        """Missing config file raises SystemExit."""
        (tmp_path / ".orca").mkdir()
        with pytest.raises(SystemExit):
            resolve_config_path(tmp_path, "nonexistent")

    def test_missing_external_raises(self, tmp_path: Path) -> None:
        """Missing external flow file raises SystemExit."""
        with pytest.raises(SystemExit):
            resolve_config_path(tmp_path, "/nonexistent/flow.yml")
