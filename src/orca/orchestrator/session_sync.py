from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionManifest:
    """Read/write .orca-state/runs/{branch}/{workflow}/sessions.json."""

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
        log_path: str = "",
    ) -> None:
        entries = self.read()
        entry: dict[str, Any] = {
            "issue_id": issue_id,
            "state": state,
            "session_id": session_id,
            "worktree_path": worktree_path,
            "started_at": started_at,
            "completed_at": None,
        }
        if log_path:
            entry["log_path"] = log_path
        entries.append(entry)
        self._write(entries)

    def update_log_path(self, session_id: str, log_path: str) -> None:
        """Store the log file path for a session."""
        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                entry["log_path"] = log_path
                self._write(entries)
                return

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

    def update_result_error(self, session_id: str, error: str | None) -> None:
        """Store or clear a result validation error on a session entry."""
        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                if error:
                    entry["result_error"] = error
                else:
                    entry.pop("result_error", None)
                self._write(entries)
                return
        logger.warning("update_result_error: session %s not found in manifest", session_id)

    def update_progress(self, session_id: str, progress: int, status: str | None) -> None:
        """Update progress and status for a session."""
        from datetime import UTC, datetime

        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                entry["progress"] = progress
                entry["status"] = status
                entry["progress_updated_at"] = datetime.now(UTC).isoformat()
                self._write(entries)
                return
        logger.warning("update_progress: session %s not found in manifest", session_id)

    def mark_orphans_completed(self, completed_at: str, *, interrupted: bool = False, failed: bool = False) -> int:
        """Mark all incomplete sessions as completed (orphans from a crashed or stopped run)."""
        entries = self.read()
        count = 0
        for entry in entries:
            if entry["completed_at"] is None:
                entry["completed_at"] = completed_at
                if interrupted:
                    entry["interrupted"] = True
                if failed:
                    entry["failed"] = True
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
