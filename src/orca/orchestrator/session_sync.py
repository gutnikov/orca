from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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

    def update_worktree_path(self, session_id: str, worktree_path: str) -> None:
        """Update the worktree_path for a session (e.g. after worktree creation resolves the real path)."""
        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                if entry["worktree_path"] != worktree_path:
                    entry["worktree_path"] = worktree_path
                    self._write(entries)
                return
        logger.warning("update_worktree_path: session %s not found in manifest", session_id)

    def mark_completed(self, session_id: str, completed_at: str) -> None:
        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                entry["completed_at"] = completed_at
                break
        else:
            logger.warning("mark_completed: session %s not found in manifest", session_id)
        self._write(entries)

    def mark_orphans_completed(self, completed_at: str) -> int:
        """Mark all incomplete sessions as completed (orphans from a crashed run)."""
        entries = self.read()
        count = 0
        for entry in entries:
            if entry["completed_at"] is None:
                entry["completed_at"] = completed_at
                count += 1
        if count:
            self._write(entries)
            logger.info("Marked %d orphan session(s) as completed", count)
        return count

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2))
        tmp.rename(self.path)


class SessionSync:
    """Lightweight session tracking (manifest only, no transcript rendering)."""

    def __init__(self, run_dir: Path) -> None:
        self.manifest = SessionManifest(run_dir)
