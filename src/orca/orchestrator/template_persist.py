"""Persist a rendered prompt to disk for later read during debug review.

Path convention: <workdir>/.orca-state/sessions/<state>-<session_id>.prompt.md
"""

from __future__ import annotations

from pathlib import Path


def persist_rendered_prompt(
    *,
    workdir: Path,
    state_id: str,
    session_id: str,
    rendered_prompt: str,
) -> Path:
    sessions_dir = workdir / ".orca-state" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{state_id}-{session_id}.prompt.md"
    path.write_text(rendered_prompt)
    return path


def rendered_prompt_path(workdir: Path, state_id: str, session_id: str) -> Path:
    return workdir / ".orca-state" / "sessions" / f"{state_id}-{session_id}.prompt.md"
