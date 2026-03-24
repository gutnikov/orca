from __future__ import annotations

from pathlib import Path
from typing import Any

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

        expected = Path.home() / ".claude" / "projects" / "-Users-alice-work-myproject--orca-worktrees-feat-db"
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

    def test_find_transcript_by_claude_session_id(self, tmp_path: Path) -> None:
        """Find transcript using claude_session_id when tracking ID doesn't match."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
            claude_projects_root=tmp_path / "claude-projects",
        )
        # Create transcript with the real Claude session ID
        projects_dir = tmp_path / "claude-projects" / "-tmp-worktrees-main"
        projects_dir.mkdir(parents=True)
        transcript = projects_dir / "real-claude-id.jsonl"
        transcript.write_text('{"type":"system"}\n')

        result = sync.find_transcript(
            session_id="tracking-uuid",
            worktree_path=Path("/tmp/worktrees/main"),
            claude_session_id="real-claude-id",
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
        """Build .orca/transcripts/{session_id}.md"""
        sync = SessionSync(
            run_dir=Path("/tmp/runs/main"),
            transcripts_dir=Path("/tmp/transcripts"),
        )

        result = sync.output_path("sess-aaa")

        expected = Path("/tmp/transcripts/sess-aaa.md")
        assert result == expected

    def test_needs_render_no_target(self, tmp_path: Path) -> None:
        """Needs render when target markdown doesn't exist."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
        )
        entry: dict[str, Any] = {"completed_at": None}

        assert sync.needs_render(entry, tmp_path / "nonexistent.md")

    def test_needs_render_completed_and_exists_no_render_state(self, tmp_path: Path) -> None:
        """Needs render when completed + exists but never synced (no render state)."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
        )
        target = tmp_path / "output.md"
        target.write_text("rendered")
        entry: dict[str, Any] = {"completed_at": "2026-03-22T10:10:00Z", "session_id": "sess-x"}

        assert sync.needs_render(entry, target)

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


class TestSessionSyncIncremental:
    def _setup_sync(self, tmp_path: Path) -> tuple[SessionSync, Path, Path]:
        """Create a SessionSync with a transcript JSONL file ready to go."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        claude_root = tmp_path / "claude-projects"
        sync = SessionSync(run_dir=run_dir, transcripts_dir=transcripts_dir, claude_projects_root=claude_root)
        sync.manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-inc",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )
        projects_path = sync.claude_projects_path(tmp_path / "worktrees" / "main")
        projects_path.mkdir(parents=True, exist_ok=True)
        jsonl_path = projects_path / "sess-inc.jsonl"
        return sync, jsonl_path, sync.output_path("sess-inc")

    def test_incremental_append(self, tmp_path: Path) -> None:
        """Two syncs produce correct combined markdown via incremental append."""
        sync, jsonl_path, output = self._setup_sync(tmp_path)
        jsonl_path.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}\n')
        sync.sync()
        assert output.exists()
        content1 = output.read_text()
        assert "Hello" in content1

        with open(jsonl_path, "a") as f:
            f.write('{"type":"assistant","message":{"content":[{"type":"text","text":"World"}]}}\n')
        sync.sync()
        content2 = output.read_text()
        assert "Hello" in content2
        assert "World" in content2
        assert "---" in content2

    def test_no_new_data_no_change(self, tmp_path: Path) -> None:
        """Sync with no new JSONL data does not modify the .md file."""
        sync, jsonl_path, output = self._setup_sync(tmp_path)
        jsonl_path.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}\n')
        sync.sync()
        mtime1 = output.stat().st_mtime
        import time

        time.sleep(0.05)
        sync.sync()
        mtime2 = output.stat().st_mtime
        assert mtime1 == mtime2

    def test_completed_session_final_render(self, tmp_path: Path) -> None:
        """Completed session gets a final render to capture trailing entries."""
        sync, jsonl_path, output = self._setup_sync(tmp_path)
        jsonl_path.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"Start"}]}}\n')
        sync.sync()
        assert "Start" in output.read_text()

        with open(jsonl_path, "a") as f:
            f.write('{"type":"result","result":"Done!","duration_ms":5000}\n')
        sync.manifest.mark_completed("sess-inc", "2026-03-22T10:10:00Z")

        sync.sync()
        content = output.read_text()
        assert "Start" in content
        assert "Done!" in content

    def test_restart_truncates_stale_md(self, tmp_path: Path) -> None:
        """A fresh SessionSync (offset=0) truncates an existing .md before re-rendering."""
        sync, jsonl_path, output = self._setup_sync(tmp_path)
        jsonl_path.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"Fresh"}]}}\n')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("STALE CONTENT\n")
        sync.sync()
        content = output.read_text()
        assert "Fresh" in content
        assert "STALE" not in content


class TestSessionSyncSync:
    def test_sync_renders_new_session(self, tmp_path: Path) -> None:
        """Sync renders a transcript to markdown for a new session."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        claude_root = tmp_path / "claude-projects"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=claude_root,
        )

        sync.manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )

        # Create the native transcript file with real content
        projects_path = sync.claude_projects_path(tmp_path / "worktrees" / "main")
        projects_path.mkdir(parents=True, exist_ok=True)
        transcript = projects_path / "sess-aaa.jsonl"
        transcript.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}\n')

        sync.sync()

        output = sync.output_path("sess-aaa")
        assert output.exists()
        content = output.read_text()
        assert "Hello" in content

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
        output = sync.output_path("sess-aaa")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("already rendered")

        sync.sync()

        # Should not overwrite
        assert output.read_text() == "already rendered"

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

        sync.sync()  # should not raise

        output = sync.output_path("sess-aaa")
        assert not output.exists()

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

        # Two entries — first has a bad worktree path that will cause an error
        sync.manifest.append(
            issue_id="issue-aaa",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/nonexistent/path",
            started_at="2026-03-22T10:00:00Z",
        )
        sync.manifest.append(
            issue_id="issue-bbb",
            state="implementing",
            session_id="sess-bbb",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )

        # Create transcript only for second entry
        projects_path = sync.claude_projects_path(tmp_path / "worktrees" / "main")
        projects_path.mkdir(parents=True, exist_ok=True)
        (projects_path / "sess-bbb.jsonl").write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Done"}]}}\n'
        )

        sync.sync()  # should not raise

        # Second entry should still be rendered
        output = sync.output_path("sess-bbb")
        assert output.exists()
        assert "Done" in output.read_text()
