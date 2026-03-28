from __future__ import annotations

from pathlib import Path

from orca.orchestrator.runner import parse_task_file


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
