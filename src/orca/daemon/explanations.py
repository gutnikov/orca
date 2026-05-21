"""File I/O for cached flow explanations.

Explanation JSONs live at <repo_root>/.orca-state/explanations/{flow}.{lang}.json.
They are written by the `orca-workflow-explain` playbook (run from a coding agent)
and read by the daemon endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ExplanationCorruptedError(Exception):
    """Raised when an explanation file exists but cannot be parsed as JSON."""


def explanation_path(repo_root: Path, flow: str, lang: str) -> Path:
    return repo_root / ".orca-state" / "explanations" / f"{flow}.{lang}.json"


def read_explanation(repo_root: Path, flow: str, lang: str) -> dict[str, Any] | None:
    """Return the parsed JSON payload, or None if the file is missing.

    Raises ExplanationCorruptedError if the file exists but contains invalid JSON.
    """
    path = explanation_path(repo_root, flow, lang)
    if not path.is_file():
        return None
    try:
        result: dict[str, Any] = json.loads(path.read_text())
        return result
    except json.JSONDecodeError as exc:
        raise ExplanationCorruptedError(f"Could not parse {path}: {exc.msg} at line {exc.lineno}") from exc
