from __future__ import annotations

from pathlib import Path

from orca.orchestrator.runner import parse_task_file


class TestParseTaskFile:
    def test_parse_title_and_description(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("Implement auth\nThis feature should support OAuth2\nand JWT tokens.")
        title, description = parse_task_file(task)
        assert title == "Implement auth"
        assert description == "This feature should support OAuth2\nand JWT tokens."

    def test_title_only(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("Simple fix")
        title, description = parse_task_file(task)
        assert title == "Simple fix"
        assert description == ""

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        task = tmp_path / "task.md"
        task.write_text("  Title with spaces  \n  Description  ")
        title, description = parse_task_file(task)
        assert title == "Title with spaces"
        assert description == "Description"
