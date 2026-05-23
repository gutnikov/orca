"""Build DebugReviewSnapshot from on-disk artifacts (rendered prompt, result,
config slice, git diff). Used by the orchestrator after a worker completes in
debug mode."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import yaml

from orca.engine.types import DebugReviewSnapshot, DiffFile, Hunk


def extract_config_slice(config_yaml: str, issue_type: str, state_id: str) -> str:
    """Extract the YAML block for types.<issue_type>.states.<state_id>."""
    try:
        doc = yaml.safe_load(config_yaml)
    except yaml.YAMLError as exc:
        return f"# Failed to parse workflow YAML: {exc}"
    types = (doc or {}).get("types", {})
    type_def = types.get(issue_type)
    if not type_def:
        return f"# State {issue_type}.{state_id} not found in workflow YAML"
    state_def = (type_def.get("states") or {}).get(state_id)
    if state_def is None:
        return f"# State {issue_type}.{state_id} not found in workflow YAML"
    sliced = {state_id: state_def}
    return yaml.safe_dump(sliced, sort_keys=False, default_flow_style=False)


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_unified_diff(diff_text: str) -> list[DiffFile]:
    """Parse unified diff text into a list of DiffFile."""
    if not diff_text.strip():
        return []

    files: list[DiffFile] = []
    lines = diff_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("diff --git "):
            i += 1
            continue
        parts = line.split(" ", 3)
        path = "?"
        if len(parts) >= 4:
            # parts[3] is the "b/<path>" component of "diff --git a/<path> b/<path>"
            after = parts[3]
            if after.startswith("b/"):
                path = after[2:]
            elif " b/" in after:
                path = after.split(" b/", 1)[1]
            else:
                path = after
        status = "modified"
        hunks: list[Hunk] = []
        i += 1
        while i < len(lines) and not lines[i].startswith("@@") and not lines[i].startswith("diff --git "):
            if lines[i].startswith("new file mode"):
                status = "added"
            elif lines[i].startswith("deleted file mode"):
                status = "deleted"
            elif lines[i].startswith("rename from "):
                status = "renamed"
            i += 1
        while i < len(lines) and lines[i].startswith("@@"):
            match = _HUNK_HEADER.match(lines[i])
            if not match:
                i += 1
                continue
            old_start = int(match.group(1))
            old_lines = int(match.group(2) or 1)
            new_start = int(match.group(3))
            new_lines = int(match.group(4) or 1)
            hunk_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("@@") and not lines[i].startswith("diff --git "):
                if lines[i].startswith((" ", "+", "-", "\\")):
                    hunk_lines.append(lines[i])
                i += 1
            hunks.append(
                Hunk(
                    old_start=old_start,
                    old_lines=old_lines,
                    new_start=new_start,
                    new_lines=new_lines,
                    lines=hunk_lines,
                )
            )
        files.append(DiffFile(path=path, status=status, hunks=hunks))
    return files


async def build_snapshot(
    *,
    worktree_path: Path,
    base_commit: str,
    rendered_prompt_path: Path,
    worker_result: dict[str, Any],
    config_path: Path,
    issue_type: str,
    state_id: str,
) -> DebugReviewSnapshot:
    """Assemble the snapshot from on-disk artifacts."""
    rendered_prompt = ""
    if rendered_prompt_path.exists():
        rendered_prompt = rendered_prompt_path.read_text()

    proc = await asyncio.create_subprocess_exec(
        "git",
        "diff",
        "--unified=3",
        f"{base_commit}..HEAD",
        cwd=str(worktree_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    diff_text = stdout.decode("utf-8", errors="replace")
    diff_files = parse_unified_diff(diff_text)

    config_yaml = config_path.read_text() if config_path.exists() else ""
    config_slice = extract_config_slice(config_yaml, issue_type, state_id)

    return DebugReviewSnapshot(
        rendered_prompt=rendered_prompt,
        worker_result=worker_result,
        config_slice=config_slice,
        diff_files=diff_files,
        base_commit=base_commit,
    )
