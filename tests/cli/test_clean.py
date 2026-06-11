"""Tests for `orca clean` on-disk classification, path safety, and temp-file exclusion."""

from __future__ import annotations

from pathlib import Path

from orca.cli.clean_cmd import (
    _classify_runs_on_disk,
    _filter_temp_files,
    _run_dir_for,
    clean_command,
)


def _make_run(state_dir: Path, branch: str, workflow: str) -> Path:
    run_dir = state_dir / "runs" / branch / workflow
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text("{}")
    return run_dir


class TestClassifyRunsOnDisk:
    def test_finds_simple_branch_runs(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        _make_run(state_dir, "main", "develop")

        terminal, active = _classify_runs_on_disk(state_dir)

        assert active == []
        assert terminal == [
            {"run_id": "main:develop", "branch": "main", "workflow": "develop", "status": "interrupted"}
        ]

    def test_finds_runs_on_slash_named_branches(self, tmp_path: Path) -> None:
        """Branches like feat/x nest one level deeper — they must still be found."""
        state_dir = tmp_path / ".orca-state"
        _make_run(state_dir, "feat/x", "develop")

        terminal, _ = _classify_runs_on_disk(state_dir)

        assert terminal == [
            {"run_id": "feat/x:develop", "branch": "feat/x", "workflow": "develop", "status": "interrupted"}
        ]

    def test_skips_dirs_without_state_json(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        (state_dir / "runs" / "main" / "develop").mkdir(parents=True)

        terminal, active = _classify_runs_on_disk(state_dir)

        assert terminal == []
        assert active == []

    def test_no_runs_dir(self, tmp_path: Path) -> None:
        assert _classify_runs_on_disk(tmp_path / ".orca-state") == ([], [])


class TestRunDirFor:
    def test_normal_run(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        run = {"branch": "main", "workflow": "develop"}
        assert _run_dir_for(state_dir, run) == state_dir / "runs" / "main" / "develop"

    def test_slash_branch(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        run = {"branch": "feat/x", "workflow": "develop"}
        assert _run_dir_for(state_dir, run) == state_dir / "runs" / "feat/x" / "develop"

    def test_empty_components_rejected(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        assert _run_dir_for(state_dir, {"branch": "", "workflow": "develop"}) is None
        assert _run_dir_for(state_dir, {"branch": "main", "workflow": ""}) is None

    def test_traversal_rejected(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        assert _run_dir_for(state_dir, {"branch": "../../etc", "workflow": "develop"}) is None
        assert _run_dir_for(state_dir, {"branch": "main", "workflow": "../.."}) is None

    def test_absolute_branch_rejected(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        assert _run_dir_for(state_dir, {"branch": "/etc", "workflow": "develop"}) is None


class TestFilterTempFiles:
    def test_no_active_runs_keeps_all(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        tmp = state_dir / ".prompt-a.tmp"
        tmp.parent.mkdir(parents=True)
        tmp.write_text("")

        assert _filter_temp_files([tmp], state_dir, []) == [tmp]

    def test_excludes_temps_under_active_worktree_and_run_dir(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".orca-state"
        active = [{"run_id": "feat/x:develop", "branch": "feat/x", "workflow": "develop", "status": "running"}]

        in_worktree = state_dir / "worktrees" / "feat/x" / ".orca-state" / ".prompt-a.tmp"
        in_run_dir = state_dir / "runs" / "feat/x" / "develop" / ".prompt-b.tmp"
        elsewhere = state_dir / "worktrees" / "other" / ".orca-state" / ".prompt-c.tmp"
        for p in (in_worktree, in_run_dir, elsewhere):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")

        kept = _filter_temp_files([in_worktree, in_run_dir, elsewhere], state_dir, active)

        assert kept == [elsewhere]


class TestCleanCommandDaemonDown:
    def test_cleans_slash_branch_run(self, tmp_path: Path, capsys) -> None:
        """Daemon down: a run on a slash-named branch must be found and removed."""
        state_dir = tmp_path / ".orca-state"
        run_dir = _make_run(state_dir, "feat/x", "develop")

        clean_command(root=tmp_path, yes=True)

        out = capsys.readouterr().out
        assert "feat/x:develop" in out
        assert "Cleaned: 1 run(s)" in out
        assert not run_dir.exists()
        # Intermediate branch dirs are pruned once empty.
        assert not (state_dir / "runs" / "feat").exists()

    def test_dry_run_deletes_nothing(self, tmp_path: Path, capsys) -> None:
        state_dir = tmp_path / ".orca-state"
        run_dir = _make_run(state_dir, "feat/x", "develop")

        clean_command(root=tmp_path, dry_run=True)

        assert "dry run" in capsys.readouterr().out
        assert run_dir.exists()
