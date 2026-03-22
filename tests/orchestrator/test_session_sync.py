from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from orca.orchestrator.session_sync import SessionManifest, SessionSync


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


class TestSessionSync:
    def test_claude_projects_path(self) -> None:
        """Derive project hash from worktree path."""
        sync = SessionSync(
            run_dir=Path("/tmp/runs/main"),
            transcripts_dir=Path("/tmp/transcripts"),
        )

        result = sync.claude_projects_path(Path("/Users/alice/work/myproject"))

        expected = Path.home() / ".claude" / "projects" / "-Users-alice-work-myproject"
        assert result == expected

    def test_claude_projects_path_nested_worktree(self) -> None:
        """Worktree paths produce their own project hash."""
        sync = SessionSync(
            run_dir=Path("/tmp/runs/main"),
            transcripts_dir=Path("/tmp/transcripts"),
        )

        result = sync.claude_projects_path(Path("/Users/alice/work/myproject/.orca/worktrees/feat/db"))

        expected = Path.home() / ".claude" / "projects" / "-Users-alice-work-myproject-.orca-worktrees-feat-db"
        assert result == expected

    def test_find_transcript_direct_path(self, tmp_path: Path) -> None:
        """Find transcript at the derived project path."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
            claude_projects_root=tmp_path / "claude-projects",
        )
        # Create transcript at expected location
        projects_dir = tmp_path / "claude-projects" / "-tmp-worktrees-main"
        projects_dir.mkdir(parents=True)
        transcript = projects_dir / "sess-aaa.jsonl"
        transcript.write_text('{"type":"system"}\n')

        result = sync.find_transcript(
            session_id="sess-aaa",
            worktree_path=Path("/tmp/worktrees/main"),
        )

        assert result == transcript

    def test_find_transcript_fallback_scan(self, tmp_path: Path) -> None:
        """Fall back to scanning all project dirs when derived path is wrong."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
            claude_projects_root=tmp_path / "claude-projects",
        )
        # Create transcript in an unexpected project dir (simulates changed hash algo)
        other_dir = tmp_path / "claude-projects" / "some-other-hash"
        other_dir.mkdir(parents=True)
        transcript = other_dir / "sess-aaa.jsonl"
        transcript.write_text('{"type":"system"}\n')

        result = sync.find_transcript(
            session_id="sess-aaa",
            worktree_path=Path("/tmp/worktrees/main"),
        )

        assert result == transcript

    def test_find_transcript_not_found(self, tmp_path: Path) -> None:
        """Return None when transcript doesn't exist anywhere."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
            claude_projects_root=tmp_path / "claude-projects",
        )
        (tmp_path / "claude-projects").mkdir(parents=True)

        result = sync.find_transcript(
            session_id="sess-aaa",
            worktree_path=Path("/tmp/worktrees/main"),
        )

        assert result is None

    def test_output_path(self) -> None:
        """Build .orca/transcripts/{issue_id}/{state}-{timestamp}.md"""
        sync = SessionSync(
            run_dir=Path("/tmp/runs/main"),
            transcripts_dir=Path("/tmp/transcripts"),
        )

        result = sync.output_path("issue-1", "implementing", "2026-03-22T10:36:00Z")

        expected = Path("/tmp/transcripts/issue-1/implementing-2026-03-22T10-36-00Z.md")
        assert result == expected

    def test_needs_render_no_target(self, tmp_path: Path) -> None:
        """Needs render when target markdown doesn't exist."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
        )
        entry: dict[str, Any] = {"completed_at": None}

        assert sync.needs_render(entry, tmp_path / "nonexistent.md")

    def test_needs_render_completed_and_exists(self, tmp_path: Path) -> None:
        """Skip render when completed and target exists."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
        )
        target = tmp_path / "output.md"
        target.write_text("rendered")
        entry: dict[str, Any] = {"completed_at": "2026-03-22T10:10:00Z"}

        assert not sync.needs_render(entry, target)

    def test_needs_render_still_running(self, tmp_path: Path) -> None:
        """Re-render when session still running even if target exists."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
        )
        target = tmp_path / "output.md"
        target.write_text("partial render")
        entry: dict[str, Any] = {"completed_at": None}

        assert sync.needs_render(entry, target)


class TestSessionSyncSync:
    def test_sync_renders_new_session(self, tmp_path: Path) -> None:
        """Sync invokes claude-code-log for a session that needs rendering."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        claude_root = tmp_path / "claude-projects"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=claude_root,
        )

        # Set up manifest with one entry
        sync.manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )

        # Create the native transcript file
        projects_path = sync.claude_projects_path(tmp_path / "worktrees" / "main")
        projects_path.mkdir(parents=True, exist_ok=True)
        transcript = projects_path / "sess-aaa.jsonl"
        transcript.write_text('{"type":"system"}\n')

        expected_output = sync.output_path("issue-1", "implementing", "2026-03-22T10:00:00Z")

        with patch("orca.orchestrator.session_sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            sync.sync()

        mock_run.assert_called_once_with(
            [
                "uv",
                "tool",
                "run",
                "claude-code-log",
                str(transcript),
                "--format",
                "md",
                "-o",
                str(expected_output),
            ],
            check=True,
            capture_output=True,
        )

    def test_sync_skips_completed_and_rendered(self, tmp_path: Path) -> None:
        """Sync skips sessions that are completed and already rendered."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=tmp_path / "claude-projects",
        )

        sync.manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )
        sync.manifest.mark_completed("sess-aaa", "2026-03-22T10:10:00Z")

        # Pre-create the rendered output
        output = sync.output_path("issue-1", "implementing", "2026-03-22T10:00:00Z")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("already rendered")

        with patch("orca.orchestrator.session_sync.subprocess.run") as mock_run:
            sync.sync()

        mock_run.assert_not_called()

    def test_sync_skips_missing_transcript(self, tmp_path: Path) -> None:
        """Sync skips sessions where native transcript doesn't exist."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=tmp_path / "claude-projects",
        )
        (tmp_path / "claude-projects").mkdir(parents=True)

        sync.manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )

        with patch("orca.orchestrator.session_sync.subprocess.run") as mock_run:
            sync.sync()  # should not raise

        mock_run.assert_not_called()

    def test_sync_continues_on_per_entry_failure(self, tmp_path: Path) -> None:
        """If one entry fails, remaining entries are still processed."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        claude_root = tmp_path / "claude-projects"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=claude_root,
        )

        # Two entries
        for sid in ["sess-aaa", "sess-bbb"]:
            sync.manifest.append(
                issue_id=f"issue-{sid}",
                state="implementing",
                session_id=sid,
                worktree_path=str(tmp_path / "worktrees" / "main"),
                started_at="2026-03-22T10:00:00Z",
            )
            projects_path = sync.claude_projects_path(tmp_path / "worktrees" / "main")
            projects_path.mkdir(parents=True, exist_ok=True)
            (projects_path / f"{sid}.jsonl").write_text('{"type":"system"}\n')

        with patch("orca.orchestrator.session_sync.subprocess.run") as mock_run:
            # First call fails, second succeeds
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, "claude-code-log"),
                subprocess.CompletedProcess(args=[], returncode=0),
            ]
            sync.sync()  # should not raise

        assert mock_run.call_count == 2
