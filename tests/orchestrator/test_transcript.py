from __future__ import annotations

import json
from pathlib import Path

from orca.orchestrator.transcript import render_incremental, render_transcript


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

    def test_session_header(self, tmp_path: Path) -> None:
        """System/init entry renders a session header with model and cwd."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": "abc-12345678",
                    "model": "claude-opus-4-6",
                    "cwd": "/Users/test/project",
                },
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}},
            ],
        )
        md = render_transcript(path)
        assert "# Session `abc-1234..." in md
        assert "claude-opus-4-6" in md
        assert "/Users/test/project" in md
        assert "Hi" in md

    def test_skips_non_init_system_entries(self, tmp_path: Path) -> None:
        """Non-init system entries are skipped."""
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "system", "subtype": "hook_started", "hook_name": "test"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}},
            ],
        )
        md = render_transcript(path)
        assert "hook" not in md
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
        # Session header present
        assert "# Session" in md

    def test_turn_separators(self, tmp_path: Path) -> None:
        """Consecutive assistant turns get a --- separator."""
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "First"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Second"}]}},
            ],
        )
        md = render_transcript(path)
        assert "First" in md
        assert "Second" in md
        # Separator between the two assistant blocks
        first_idx = md.index("First")
        second_idx = md.index("Second")
        separator_section = md[first_idx:second_idx]
        assert "---" in separator_section

    def test_no_separator_between_tool_use_and_result(self, tmp_path: Path) -> None:
        """No separator between assistant tool_use and user tool_result."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "x.py"}}]},
                },
                {
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "content": "file contents"}]},
                },
            ],
        )
        md = render_transcript(path)
        # No --- between tool call and result
        assert md.count("---") == 0

    def test_token_usage(self, tmp_path: Path) -> None:
        """Token usage from assistant messages is rendered."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Hello"}],
                        "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 200},
                    },
                },
            ],
        )
        md = render_transcript(path)
        assert "in: 100" in md
        assert "out: 50" in md
        assert "cache_read: 200" in md

    def test_ansi_stripping(self, tmp_path: Path) -> None:
        """ANSI escape codes are stripped from tool results."""
        ansi_text = "\x1b[32mgreen\x1b[0m normal"
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": ansi_text}]}},
            ],
        )
        md = render_transcript(path)
        assert "green normal" in md
        assert "\x1b" not in md

    def test_image_placeholder(self, tmp_path: Path) -> None:
        """Image content blocks render as placeholders."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png"}}]
                    },
                },
            ],
        )
        md = render_transcript(path)
        assert "[Image: image/png]" in md

    def test_image_in_tool_result(self, tmp_path: Path) -> None:
        """Image items in tool results render as placeholders."""
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "content": [
                                    {"type": "text", "text": "screenshot taken"},
                                    {"type": "image", "source": {"media_type": "image/jpeg"}},
                                ],
                            }
                        ]
                    },
                },
            ],
        )
        md = render_transcript(path)
        assert "screenshot taken" in md
        assert "[Image: image/jpeg]" in md

    def test_line_number_stripping(self, tmp_path: Path) -> None:
        """Read tool line number prefixes are stripped from tool results."""
        content = "     1\u2192def hello():\n     2\u2192    return 'hi'\n"
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": content}]}},
            ],
        )
        md = render_transcript(path)
        assert "def hello():" in md
        assert "1\u2192" not in md


class TestRenderIncremental:
    def _write_jsonl(self, tmp_path: Path, entries: list[dict[str, object]]) -> Path:
        path = tmp_path / "test.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        return path

    def test_from_zero_matches_full_render(self, tmp_path: Path) -> None:
        """render_incremental from offset=0 produces same output as render_transcript."""
        entries: list[dict[str, object]] = [
            {"type": "system", "subtype": "init", "session_id": "abc", "model": "claude"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "OK"}]}},
        ]
        path = self._write_jsonl(tmp_path, entries)
        full = render_transcript(path)
        md, new_offset, new_last_type = render_incremental(path, 0, "")
        assert md == full
        assert new_offset > 0
        assert new_last_type == "user"

    def test_incremental_two_chunks(self, tmp_path: Path) -> None:
        """Two incremental calls produce same result as one full render."""
        path = tmp_path / "test.jsonl"
        entry1 = {"type": "assistant", "message": {"content": [{"type": "text", "text": "First"}]}}
        path.write_text(json.dumps(entry1) + "\n")
        md1, offset, last_type = render_incremental(path, 0, "")
        assert "First" in md1

        entry2 = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Second"}]}}
        with open(path, "a") as f:
            f.write(json.dumps(entry2) + "\n")
        md2, offset2, last_type2 = render_incremental(path, offset, last_type)
        assert "Second" in md2
        assert offset2 > offset
        assert "---" in md2

    def test_no_new_data_returns_empty(self, tmp_path: Path) -> None:
        """When no new data exists, returns empty string."""
        entry: dict[str, object] = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}
        path = self._write_jsonl(tmp_path, [entry])
        _, offset, last_type = render_incremental(path, 0, "")
        md, offset2, last_type2 = render_incremental(path, offset, last_type)
        assert md == ""
        assert offset2 == offset
        assert last_type2 == last_type

    def test_truncated_line_not_consumed(self, tmp_path: Path) -> None:
        """A partial line at EOF is not consumed -- offset stays before it."""
        path = tmp_path / "test.jsonl"
        complete = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done"}]}})
        partial = '{"type": "assistant", "message": {"content": [{"type": "te'
        path.write_text(complete + "\n" + partial)
        md, offset, _ = render_incremental(path, 0, "")
        assert "Done" in md
        assert offset == len(complete.encode("utf-8")) + 1

    def test_file_smaller_than_offset(self, tmp_path: Path) -> None:
        """If file is smaller than offset, reset to 0."""
        path = self._write_jsonl(
            tmp_path,
            [{"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}],
        )
        md, offset, last_type = render_incremental(path, 99999, "assistant")
        assert "Hi" in md
        assert offset > 0
        assert last_type == "assistant"
