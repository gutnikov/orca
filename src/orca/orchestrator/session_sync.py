from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SessionManifest:
    """Read/write .orca/runs/{branch}/sessions.json."""

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "sessions.json"

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())  # type: ignore[no-any-return]

    def append(
        self,
        *,
        issue_id: str,
        state: str,
        session_id: str,
        worktree_path: str,
        started_at: str,
    ) -> None:
        entries = self.read()
        entries.append(
            {
                "issue_id": issue_id,
                "state": state,
                "session_id": session_id,
                "worktree_path": worktree_path,
                "started_at": started_at,
                "completed_at": None,
            }
        )
        self._write(entries)

    def mark_completed(self, session_id: str, completed_at: str) -> None:
        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                entry["completed_at"] = completed_at
                break
        self._write(entries)

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2))
        tmp.rename(self.path)
