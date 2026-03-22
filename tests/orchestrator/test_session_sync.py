from __future__ import annotations

from pathlib import Path

from orca.orchestrator.session_sync import SessionManifest


class TestSessionManifest:
    def test_append_and_read(self, tmp_path: Path) -> None:
        """Append an entry, read it back."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        entries = manifest.read()

        assert len(entries) == 1
        assert entries[0]["issue_id"] == "issue-1"
        assert entries[0]["session_id"] == "sess-aaa"
        assert entries[0]["worktree_path"] == "/tmp/wt/main"
        assert entries[0]["completed_at"] is None

    def test_multiple_entries(self, tmp_path: Path) -> None:
        """Append two entries, read both back."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="planning",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-bbb",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:05:00Z",
        )

        entries = manifest.read()

        assert len(entries) == 2
        assert entries[0]["session_id"] == "sess-aaa"
        assert entries[1]["session_id"] == "sess-bbb"

    def test_mark_completed(self, tmp_path: Path) -> None:
        """Mark a session as completed, verify completed_at is set."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        manifest.mark_completed("sess-aaa", "2026-03-22T10:10:00Z")

        entries = manifest.read()
        assert entries[0]["completed_at"] == "2026-03-22T10:10:00Z"

    def test_read_empty(self, tmp_path: Path) -> None:
        """Read from nonexistent file returns empty list."""
        manifest = SessionManifest(tmp_path / "runs" / "main")

        entries = manifest.read()

        assert entries == []

    def test_mark_completed_unknown_session(self, tmp_path: Path) -> None:
        """mark_completed with unknown session_id is a no-op."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        manifest.mark_completed("nonexistent", "2026-03-22T10:10:00Z")

        entries = manifest.read()
        assert entries[0]["completed_at"] is None

    def test_atomic_write(self, tmp_path: Path) -> None:
        """No .tmp file left after write."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        assert manifest.path.exists()
        assert not manifest.path.with_suffix(".tmp").exists()
