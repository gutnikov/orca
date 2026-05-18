from pathlib import Path
from typing import Any

import pytest

from orca.orchestrator.template import TemplateRenderError, render_prompt, render_prompt_string


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

    def test_result_example_rendering(self, tmp_path: Path) -> None:
        """Prompts can render a concrete result example separate from the schema."""
        template_content = "{{ result_example | tojson(indent=2) }}"
        template_file = tmp_path / "template.md"
        template_file.write_text(template_content)

        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        result_format: dict[str, Any] = {
            "outcome": {"type": "enum", "values": ["done"], "description": "Outcome"},
            "summary": {"type": "string", "description": "Summary"},
            "changed_files": {"type": "list", "items": "string", "description": "Files"},
        }
        result_path = Path("/tmp/result.txt")

        output = render_prompt(template_file, tmp_path, issue, result_format, result_path)

        assert '"outcome": "done"' in output
        assert '"summary": "\\u003csummary\\u003e"' in output
        assert '"changed_files": []' in output

    def test_render_error_includes_template_path_and_dict_guidance(self, tmp_path: Path) -> None:
        """Dict method/key shadowing failures should be actionable."""
        template_file = tmp_path / "template.md"
        template_file.write_text("{{ result_format.outcome.values | tojson }}")

        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        result_format: dict[str, Any] = {
            "outcome": {"type": "enum", "values": ["done"], "description": "Outcome"},
        }

        with pytest.raises(TemplateRenderError) as exc_info:
            render_prompt(template_file, tmp_path, issue, result_format, Path("/tmp/result.txt"))

        message = str(exc_info.value)
        assert str(template_file) in message
        assert "result_format['outcome']['values']" in message

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

        assert "PROGRESS:" in output
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

        assert "PROGRESS:" not in output


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


class TestRenderPromptString:
    def test_inline_basic_rendering(self) -> None:
        source = "Title: {{ issue.fields.title }}\nResult path: {{ result_path }}"
        issue: dict[str, Any] = {
            "fields": {"title": "Fix bug"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }
        output = render_prompt_string(source, issue, {}, Path("/tmp/result.txt"))
        assert "Fix bug" in output
        assert "/tmp/result.txt" in output

    def test_inline_render_error_wraps_exception(self) -> None:
        bad_source = "{{ issue.fields.title.nonexistent() }}"
        issue: dict[str, Any] = {"fields": {"title": "hi"}, "event_log": []}
        with pytest.raises(TemplateRenderError):
            render_prompt_string(bad_source, issue, {}, Path("/tmp/result.txt"))

    def test_inline_result_file_warning_appended(self) -> None:
        output = render_prompt_string(
            "hello",
            {"fields": {}, "event_log": []},
            {},
            Path("/tmp/result.txt"),
        )
        assert "IMPORTANT" in output
        assert "result file" in output
