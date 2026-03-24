from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from orca.orchestrator.transcript import render_incremental

logger = logging.getLogger(__name__)


def _extract_session_id_from_log(candidates: list[Path], started_at: str) -> str | None:
    """Extract sessionId from the best-matching session log file.

    Picks the candidate whose filename timestamp is closest to started_at,
    then reads the first few lines to find the sessionId field.
    """
    best: Path | None = None
    if len(candidates) == 1:
        best = candidates[0]
    elif started_at:
        # Parse started_at and match to filename timestamp (e.g. "implementing-20260323T194801.jsonl")
        try:
            target = datetime.fromisoformat(started_at)
        except ValueError:
            best = candidates[-1]  # fallback to latest
        else:
            best_delta = float("inf")
            for c in candidates:
                # Extract timestamp from filename: {state}-{YYYYMMDDTHHMMSS}.jsonl
                stem = c.stem  # e.g. "implementing-20260323T194801"
                parts = stem.rsplit("-", 1)
                if len(parts) != 2:
                    continue
                try:
                    file_dt = datetime.strptime(parts[1], "%Y%m%dT%H%M%S")
                    file_dt = file_dt.replace(tzinfo=target.tzinfo)
                    delta = abs((file_dt - target).total_seconds())
                    if delta < best_delta:
                        best_delta = delta
                        best = c
                except ValueError:
                    continue
    if best is None:
        best = candidates[-1]

    # Read first few lines to find sessionId
    try:
        with best.open() as f:
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                    sid = msg.get("sessionId") or msg.get("session_id")
                    if sid:
                        return str(sid)
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        pass
    return None


@dataclass
class _SessionRenderState:
    byte_offset: int = 0
    last_type: str = ""


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

    def mark_completed(self, session_id: str, completed_at: str, *, claude_session_id: str | None = None) -> None:
        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                entry["completed_at"] = completed_at
                if claude_session_id:
                    entry["claude_session_id"] = claude_session_id
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

    def backfill_claude_session_ids(self) -> int:
        """Populate claude_session_id for entries missing it by scanning session log files.

        Matches manifest entries to {worktree}/.orca/sessions/{state}-*.jsonl files
        by state name, then extracts the real sessionId from the first JSON line.
        """
        entries = self.read()
        count = 0
        for entry in entries:
            if entry.get("claude_session_id"):
                continue
            worktree = Path(entry["worktree_path"])
            sessions_dir = worktree / ".orca" / "sessions"
            if not sessions_dir.is_dir():
                continue
            state = entry.get("state", "")
            candidates = sorted(sessions_dir.glob(f"{state}-*.jsonl"))
            if not candidates:
                continue
            # Pick best match by timestamp proximity to started_at
            claude_id = _extract_session_id_from_log(candidates, entry.get("started_at", ""))
            if claude_id:
                entry["claude_session_id"] = claude_id
                count += 1
        if count:
            self._write(entries)
            logger.info("Backfilled claude_session_id for %d session(s)", count)
        return count

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
        self._render_states: dict[str, _SessionRenderState] = {}

    def claude_projects_path(self, worktree_path: Path) -> Path:
        """Derive ~/.claude/projects/{hash}/ from worktree path."""
        project_hash = str(worktree_path).replace("/", "-").replace(".", "-")
        return self.claude_projects_root / project_hash

    def find_transcript(
        self, *, session_id: str, worktree_path: Path, claude_session_id: str | None = None
    ) -> Path | None:
        """Find native transcript, trying claude_session_id first, then tracking id."""
        project_dir = self.claude_projects_path(worktree_path)

        # Try the real Claude session ID first (most reliable)
        if claude_session_id:
            candidate = project_dir / f"{claude_session_id}.jsonl"
            if candidate.exists():
                return candidate

        # Try tracking UUID (unlikely to match, but cheap check)
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate

        return None

    def output_path(self, session_id: str) -> Path:
        """Build .orca/transcripts/{session_id}.md"""
        return self.transcripts_dir / f"{session_id}.md"

    def needs_render(self, entry: dict[str, Any], target: Path) -> bool:
        """True if session needs syncing: not yet rendered, or has unread bytes."""
        if not target.exists():
            return True
        if entry["completed_at"] is None:
            return True
        # Completed + .md exists: check if there are unread bytes (final render)
        session_id = entry.get("session_id", "")
        rs = self._render_states.get(session_id)
        if rs is None:
            # Never synced by us — still needs a full render if JSONL exists
            return True
        # If we have render state, check if JSONL has more bytes than we've read
        transcript = self.find_transcript(
            session_id=session_id,
            worktree_path=Path(entry["worktree_path"]),
            claude_session_id=entry.get("claude_session_id"),
        )
        if transcript is None:
            return False
        return transcript.stat().st_size > rs.byte_offset

    def sync(self) -> None:
        """Render new/updated session transcripts to markdown."""
        entries = self.manifest.read()
        for entry in entries:
            try:
                self._sync_entry(entry)
            except Exception:
                logger.exception("Failed to render session %s", entry.get("session_id"))

    def _sync_entry(self, entry: dict[str, Any]) -> None:
        target = self.output_path(entry["session_id"])
        if not self.needs_render(entry, target):
            return

        transcript = self.find_transcript(
            session_id=entry["session_id"],
            worktree_path=Path(entry["worktree_path"]),
            claude_session_id=entry.get("claude_session_id"),
        )
        if transcript is None:
            logger.warning(
                "Native transcript not found for session %s",
                entry["session_id"],
            )
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        session_id = entry["session_id"]
        rs = self._render_states.get(session_id)

        if rs is None:
            # First sync for this session — if stale .md exists, truncate it
            rs = _SessionRenderState()
            self._render_states[session_id] = rs
            if target.exists():
                target.write_text("")

        md, new_offset, new_last_type = render_incremental(transcript, rs.byte_offset, rs.last_type)

        if not md:
            return

        rs.byte_offset = new_offset
        rs.last_type = new_last_type

        if target.exists() and target.stat().st_size > 0:
            with open(target, "a") as f:
                f.write("\n\n" + md)
        else:
            target.write_text(md)
