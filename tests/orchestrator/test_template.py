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


class TestRenderInsightsPrompt:
    def test_renders_with_insights_context(self, tmp_path: Path) -> None:
        """Template receives state, transcripts, mode, insights_so_far, output_path."""
        template = tmp_path / "insights.md.j2"
        template.write_text(
            "Mode: {{ mode }}\nIssues: {{ state.issues | length }}\n"
            "Transcripts: {{ transcripts | length }}\n"
            "Output: {{ output_path }}\n"
            "Prior: {{ insights_so_far[:5] }}"
        )

        from orca.orchestrator.template import render_insights_prompt

        result = render_insights_prompt(
            template_path=template,
            state={"issues": {"i1": {"state": "coding"}, "i2": {"state": "done"}}},
            transcripts={"s1": "transcript content"},
            mode="incremental",
            insights_so_far="prior observations",
            output_path="/tmp/insights.md",
        )

        assert "Mode: incremental" in result
        assert "Issues: 2" in result
        assert "Transcripts: 1" in result
        assert "Output: /tmp/insights.md" in result
        assert "Prior: prior" in result

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        from orca.orchestrator.template import render_insights_prompt

        with pytest.raises(FileNotFoundError):
            render_insights_prompt(
                template_path=tmp_path / "nonexistent.j2",
                state={},
                transcripts={},
                mode="incremental",
                insights_so_far="",
                output_path="/tmp/insights.md",
            )
