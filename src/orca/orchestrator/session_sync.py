from __future__ import annotations

import json
import logging
import subprocess
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

    def mark_completed(self, session_id: str, completed_at: str) -> None:
        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                entry["completed_at"] = completed_at
                break
        else:
            logger.warning("mark_completed: session %s not found in manifest", session_id)
        self._write(entries)

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2))
        tmp.rename(self.path)


class SessionSync:
    """Render Claude Code session transcripts to markdown."""

    def __init__(
        self,
        run_dir: Path,
        transcripts_dir: Path,
        claude_projects_root: Path | None = None,
    ) -> None:
        self.manifest = SessionManifest(run_dir)
        self.transcripts_dir = transcripts_dir
        self.claude_projects_root = claude_projects_root or Path.home() / ".claude" / "projects"

    def claude_projects_path(self, worktree_path: Path) -> Path:
        """Derive ~/.claude/projects/{hash}/ from worktree path."""
        project_hash = str(worktree_path).replace("/", "-")
        return self.claude_projects_root / project_hash

    def find_transcript(self, *, session_id: str, worktree_path: Path) -> Path | None:
        """Find native transcript, trying derived path then fallback scan."""
        filename = f"{session_id}.jsonl"

        # Try derived path first
        derived = self.claude_projects_path(worktree_path) / filename
        if derived.exists():
            return derived

        # Fallback: scan all project directories
        if self.claude_projects_root.exists():
            for project_dir in self.claude_projects_root.iterdir():
                if not project_dir.is_dir():
                    continue
                candidate = project_dir / filename
                if candidate.exists():
                    logger.info(
                        "Transcript %s found via fallback scan at %s",
                        session_id,
                        candidate,
                    )
                    return candidate

        return None

    def output_path(self, issue_id: str, state: str, started_at: str) -> Path:
        """Build .orca/transcripts/{issue_id}/{state}-{timestamp}.md"""
        safe_ts = started_at.replace(":", "-")
        return self.transcripts_dir / issue_id / f"{state}-{safe_ts}.md"

    def needs_render(self, entry: dict[str, Any], target: Path) -> bool:
        """True if session is still running or completed but not yet rendered."""
        if not target.exists():
            return True
        return entry["completed_at"] is None

    def sync(self) -> None:
        """Render new/updated session transcripts to markdown."""
        entries = self.manifest.read()
        for entry in entries:
            try:
                self._sync_entry(entry)
            except Exception:
                logger.exception("Failed to render session %s", entry.get("session_id"))

    def _sync_entry(self, entry: dict[str, Any]) -> None:
        target = self.output_path(entry["issue_id"], entry["state"], entry["started_at"])
        if not self.needs_render(entry, target):
            return

        transcript = self.find_transcript(
            session_id=entry["session_id"],
            worktree_path=Path(entry["worktree_path"]),
        )
        if transcript is None:
            logger.warning(
                "Native transcript not found for session %s",
                entry["session_id"],
            )
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "uv",
                "tool",
                "run",
                "claude-code-log",
                str(transcript),
                "--format",
                "md",
                "-o",
                str(target),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
