from pathlib import Path

from orca.orchestrator.template_persist import (
    persist_rendered_prompt,
    rendered_prompt_path,
)


def test_persist_rendered_prompt_writes_to_expected_path(tmp_path: Path) -> None:
    workdir = tmp_path
    state_id = "implementing"
    session_id = "session-1"
    rendered = "# Hello\nThis is the prompt."

    path = persist_rendered_prompt(
        workdir=workdir,
        state_id=state_id,
        session_id=session_id,
        rendered_prompt=rendered,
    )

    expected = workdir / ".orca-state" / "sessions" / f"{state_id}-{session_id}.prompt.md"
    assert path == expected
    assert path.read_text() == rendered


def test_persist_rendered_prompt_creates_parent_dir(tmp_path: Path) -> None:
    workdir = tmp_path / "fresh"
    path = persist_rendered_prompt(
        workdir=workdir,
        state_id="s",
        session_id="sess",
        rendered_prompt="x",
    )
    assert path.exists()
    assert path.read_text() == "x"


def test_rendered_prompt_path_matches_persist(tmp_path: Path) -> None:
    expected = persist_rendered_prompt(workdir=tmp_path, state_id="s", session_id="sid", rendered_prompt="y")
    actual = rendered_prompt_path(tmp_path, "s", "sid")
    assert actual == expected
