"""Render Claude Code JSONL transcripts to markdown.

Parses native transcript JSONL files (from ~/.claude/projects/) and produces
a readable markdown document showing the conversation flow, tool calls, and results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Max characters to show for tool inputs/outputs before truncating
_MAX_TOOL_CONTENT = 2000


def render_transcript(jsonl_path: Path) -> str:
    """Read a JSONL transcript file and return a markdown string."""
    entries: list[dict[str, Any]] = []
    for line in jsonl_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return _render_entries(entries)


def _render_entries(entries: list[dict[str, Any]]) -> str:
    """Render a list of parsed JSONL entries to markdown."""
    parts: list[str] = []

    for entry in entries:
        entry_type = entry.get("type", "")

        if entry_type == "assistant":
            parts.extend(_render_assistant(entry))
        elif entry_type == "user":
            parts.extend(_render_user(entry))
        elif entry_type == "result":
            parts.extend(_render_result(entry))

    return "\n\n".join(parts) + "\n" if parts else ""


def _render_assistant(entry: dict[str, Any]) -> list[str]:
    """Render assistant message content blocks."""
    parts: list[str] = []
    content = entry.get("message", {}).get("content", [])

    for block in content:
        block_type = block.get("type", "")

        if block_type == "text":
            text = block.get("text", "")
            if text.strip():
                parts.append(f"**Assistant:**\n\n{text}")

        elif block_type == "tool_use":
            parts.append(_render_tool_use(block))

        elif block_type == "thinking":
            thinking = block.get("thinking", "")
            if thinking.strip():
                preview = thinking[:200].replace("\n", " ")
                if len(thinking) > 200:
                    preview += "..."
                parts.append(f"<details>\n<summary>Thinking: {preview}</summary>\n\n{thinking}\n\n</details>")

    return parts


def _render_tool_use(block: dict[str, Any]) -> str:
    """Render a tool_use block."""
    name = block.get("name", "unknown")
    tool_input = block.get("input", {})

    if name == "Bash":
        cmd = tool_input.get("command", "")
        desc = tool_input.get("description", "")
        header = f"**Tool: Bash** — {desc}" if desc else "**Tool: Bash**"
        return f"{header}\n\n```bash\n{_truncate(cmd)}\n```"

    if name == "Read":
        fp = tool_input.get("file_path", "")
        return f"**Tool: Read** `{fp}`"

    if name == "Write":
        fp = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        lang = _lang_from_path(fp)
        return f"**Tool: Write** `{fp}`\n\n```{lang}\n{_truncate(content)}\n```"

    if name == "Edit":
        fp = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        lang = _lang_from_path(fp)
        return f"**Tool: Edit** `{fp}`\n\n```{lang}\n// old:\n{_truncate(old)}\n// new:\n{_truncate(new)}\n```"

    if name in ("Glob", "Grep"):
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"**Tool: {name}** `{pattern}`" + (f" in `{path}`" if path else "")

    # Generic tool
    input_str = json.dumps(tool_input, indent=2)
    return f"**Tool: {name}**\n\n```json\n{_truncate(input_str)}\n```"


def _render_user(entry: dict[str, Any]) -> list[str]:
    """Render user message content blocks (mostly tool results)."""
    parts: list[str] = []
    content = entry.get("message", {}).get("content", [])

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type", "")

        if block_type == "tool_result":
            parts.append(_render_tool_result(block))
        elif block_type == "text":
            text = block.get("text", "")
            if text.strip():
                parts.append(f"**User:**\n\n{text}")

    return parts


def _render_tool_result(block: dict[str, Any]) -> str:
    """Render a tool_result block."""
    is_error = block.get("is_error", False)
    content = block.get("content", "")
    prefix = "**Error:**" if is_error else "**Result:**"

    if isinstance(content, str):
        if not content.strip():
            return f"{prefix} *(empty)*"
        return f"{prefix}\n\n```\n{_truncate(content)}\n```"

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        combined = "\n".join(text_parts)
        if not combined.strip():
            return f"{prefix} *(empty)*"
        return f"{prefix}\n\n```\n{_truncate(combined)}\n```"

    return f"{prefix} *(unknown format)*"


def _render_result(entry: dict[str, Any]) -> list[str]:
    """Render the final result entry."""
    result_text = entry.get("result", "")
    cost = entry.get("total_cost_usd")
    duration = entry.get("duration_ms")
    num_turns = entry.get("num_turns")

    parts: list[str] = []
    if result_text:
        parts.append(f"---\n\n**Final Result:**\n\n{result_text}")

    meta_parts: list[str] = []
    if cost is not None:
        meta_parts.append(f"Cost: ${cost:.4f}")
    if duration is not None:
        meta_parts.append(f"Duration: {duration / 1000:.1f}s")
    if num_turns is not None:
        meta_parts.append(f"Turns: {num_turns}")

    if meta_parts:
        parts.append(f"*{' | '.join(meta_parts)}*")

    return parts


def _truncate(text: str, max_len: int = _MAX_TOOL_CONTENT) -> str:
    """Truncate text with an indicator if too long."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n... ({len(text) - max_len} chars truncated)"


def _lang_from_path(path: str) -> str:
    """Guess language hint from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".json": "json",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".md": "markdown",
        ".sh": "bash",
        ".rs": "rust",
        ".go": "go",
        ".rb": "ruby",
        ".java": "java",
        ".html": "html",
        ".css": "css",
        ".sql": "sql",
        ".toml": "toml",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return ""
