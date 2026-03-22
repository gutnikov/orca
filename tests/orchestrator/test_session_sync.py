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
