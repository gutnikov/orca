from pathlib import Path
from typing import Any

import pytest

from orca.orchestrator.template import render_prompt


class TestRenderPrompt:
    def test_basic_rendering(self, tmp_path: Path) -> None:
        """Test basic variable rendering."""
        template_content = "Title: {{ issue.fields.title }}\nResult path: {{ result_path }}"
        template_file = tmp_path / "template.md"
        template_file.write_text(template_content)

        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        result_format: dict[str, Any] = {}
        result_path = Path("/tmp/result.txt")

        output = render_prompt(template_file, tmp_path, issue, result_format, result_path)

        assert "Fix bug" in output
        assert "/tmp/result.txt" in output

    def test_event_log_rendering(self, tmp_path: Path) -> None:
        """Test rendering event_log iteration."""
        template_content = "{% for event in issue.event_log %}Event: {{ event.type }}\n{% endfor %}"
        template_file = tmp_path / "template.md"
        template_file.write_text(template_content)

        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [{"type": "created"}],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        result_format: dict[str, Any] = {}
        result_path = Path("/tmp/result.txt")

        output = render_prompt(template_file, tmp_path, issue, result_format, result_path)

        assert "created" in output

    def test_result_format_rendering(self, tmp_path: Path) -> None:
        """Test rendering result_format iteration."""
        template_content = "{% for field, desc in result_format.items() %}{{ field }}: {{ desc }}\n{% endfor %}"
        template_file = tmp_path / "template.md"
        template_file.write_text(template_content)

        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        result_format: dict[str, Any] = {"status": "Success or failure"}
        result_path = Path("/tmp/result.txt")

        output = render_prompt(template_file, tmp_path, issue, result_format, result_path)

        assert "status" in output
        assert "Success or failure" in output

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        """Test that missing template raises FileNotFoundError."""
        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        result_format: dict[str, Any] = {}
        result_path = Path("/tmp/result.txt")

        with pytest.raises(FileNotFoundError):
            render_prompt(
                tmp_path / "nonexistent.md",
                tmp_path,
                issue,
                result_format,
                result_path,
            )

    def test_result_file_warning_appended(self, tmp_path: Path) -> None:
        """Rendered prompt includes the result-file termination warning."""
        template_content = "Do the thing. Write result to {{ result_path }}."
        template_file = tmp_path / "template.md"
        template_file.write_text(template_content)

        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        result_format: dict[str, Any] = {}
        result_path = Path("/tmp/result.json")

        output = render_prompt(template_file, tmp_path, issue, result_format, result_path)

        assert "final action" in output.lower()
        assert "terminate this session" in output.lower()


class TestProgressInjection:
    def test_progress_instruction_appended_when_enabled(self, tmp_path: Path) -> None:
        template_file = tmp_path / "template.md"
        template_file.write_text("Do the work.")

        issue: dict[str, Any] = {
            "fields": {"title": "Test"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }

        output = render_prompt(template_file, tmp_path, issue, {}, Path("/tmp/result.json"), progress=True)

        assert "<!-- PROGRESS:" in output
        assert "periodically report your progress" in output.lower()

    def test_progress_instruction_not_appended_by_default(self, tmp_path: Path) -> None:
        template_file = tmp_path / "template.md"
        template_file.write_text("Do the work.")

        issue: dict[str, Any] = {
            "fields": {"title": "Test"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }

        output = render_prompt(template_file, tmp_path, issue, {}, Path("/tmp/result.json"))

        assert "<!-- PROGRESS:" not in output


class TestRenderPromptSubdir:
    def test_subdirectory_template(self, tmp_path: Path) -> None:
        """Test loading template from subdirectory."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        template_content = "Title: {{ issue.fields.title }}"
        template_file = prompts_dir / "template.md"
        template_file.write_text(template_content)

        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        result_format: dict[str, Any] = {}
        result_path = Path("/tmp/result.txt")

        output = render_prompt(template_file, tmp_path, issue, result_format, result_path)

        assert "Fix bug" in output
