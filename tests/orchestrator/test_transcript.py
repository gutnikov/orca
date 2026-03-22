from __future__ import annotations

import json
from pathlib import Path

from orca.orchestrator.transcript import render_transcript


class TestRenderTranscript:
    def _write_jsonl(self, tmp_path: Path, entries: list[dict[str, object]]) -> Path:
        path = tmp_path / "test.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries))
        return path

    def test_assistant_text(self, tmp_path: Path) -> None:
        """Assistant text messages are rendered."""
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello world"}]}},
            ],
        )
        md = render_transcript(path)
        assert "**Assistant:**" in md
        assert "Hello world" in md

    def test_tool_use_bash(self, tmp_path: Path) -> None:
        """Bash tool calls show the command."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "ls -la", "description": "List files"},
                            }
                        ]
                    },
                },
            ],
        )
        md = render_transcript(path)
        assert "**Tool: Bash**" in md
        assert "ls -la" in md
        assert "List files" in md

    def test_tool_use_write(self, tmp_path: Path) -> None:
        """Write tool calls show file path and content."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Write",
                                "input": {"file_path": "hello.py", "content": "print('hi')"},
                            }
                        ]
                    },
                },
            ],
        )
        md = render_transcript(path)
        assert "**Tool: Write**" in md
        assert "hello.py" in md
        assert "print('hi')" in md

    def test_tool_use_read(self, tmp_path: Path) -> None:
        """Read tool calls show the file path."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/src/main.py"}}]
                    },
                },
            ],
        )
        md = render_transcript(path)
        assert "**Tool: Read**" in md
        assert "/src/main.py" in md

    def test_tool_result_string(self, tmp_path: Path) -> None:
        """Tool results with string content are rendered."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "content": "File created successfully"}]},
                },
            ],
        )
        md = render_transcript(path)
        assert "**Result:**" in md
        assert "File created successfully" in md

    def test_tool_result_error(self, tmp_path: Path) -> None:
        """Error tool results use the error prefix."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "content": "Permission denied", "is_error": True}]},
                },
            ],
        )
        md = render_transcript(path)
        assert "**Error:**" in md

    def test_result_entry(self, tmp_path: Path) -> None:
        """Final result entry shows summary and metadata."""
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "result", "result": "Done!", "total_cost_usd": 0.05, "duration_ms": 12000, "num_turns": 3},
            ],
        )
        md = render_transcript(path)
        assert "**Final Result:**" in md
        assert "Done!" in md
        assert "$0.0500" in md
        assert "12.0s" in md

    def test_skips_system_entries(self, tmp_path: Path) -> None:
        """System entries are not rendered."""
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "system", "subtype": "init", "session_id": "abc"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}},
            ],
        )
        md = render_transcript(path)
        assert "init" not in md
        assert "Hi" in md

    def test_thinking_block(self, tmp_path: Path) -> None:
        """Thinking blocks are rendered as blockquotes."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "thinking", "thinking": "Let me consider this carefully"}]},
                },
            ],
        )
        md = render_transcript(path)
        assert "*Thinking:*" in md
        assert "> Let me consider" in md

    def test_truncation(self, tmp_path: Path) -> None:
        """Long tool content is truncated."""
        long_content = "x" * 5000
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": long_content}]}},
            ],
        )
        md = render_transcript(path)
        assert "truncated" in md

    def test_empty_file(self, tmp_path: Path) -> None:
        """Empty file produces empty output."""
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        md = render_transcript(path)
        assert md == ""

    def test_full_conversation(self, tmp_path: Path) -> None:
        """A realistic multi-turn conversation renders correctly."""
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "system", "subtype": "init", "session_id": "abc"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "I'll create the file."}]}},
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Write",
                                "input": {"file_path": "hello.py", "content": "print('hello')"},
                            }
                        ]
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [{"type": "tool_result", "content": "File created successfully at: hello.py"}]
                    },
                },
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "File created."}]}},
                {"type": "result", "result": "File created.", "duration_ms": 5000},
            ],
        )
        md = render_transcript(path)
        # Verify ordering
        assert md.index("I'll create the file.") < md.index("Tool: Write")
        assert md.index("Tool: Write") < md.index("File created successfully")
        assert md.index("File created successfully") < md.index("Final Result")
