from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from orca.cli.eval_cmd import (
    list_evals,
    resolve_eval_paths,
    scaffold_eval,
)


def _init_git_repo(path: Path) -> Path:
    """Initialise a minimal git repo so scaffold_eval can create branches."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return path


class TestScaffoldEval:
    def test_creates_eval_directory(self, tmp_path: Path) -> None:
        scaffold_eval(repo_root=_init_git_repo(tmp_path), name="my-eval")
        assert (tmp_path / ".orca" / "evals" / "my-eval").is_dir()

    def test_creates_required_files(self, tmp_path: Path) -> None:
        scaffold_eval(repo_root=_init_git_repo(tmp_path), name="my-eval")
        eval_dir = tmp_path / ".orca" / "evals" / "my-eval"
        assert (eval_dir / "eval-flow.yml").exists()
        assert (eval_dir / "input.md").exists()
        assert (eval_dir / "assertions.md").exists()
        assert not (eval_dir / "fixtures").exists()

    def test_eval_flow_yml_is_skeleton(self, tmp_path: Path) -> None:
        scaffold_eval(repo_root=_init_git_repo(tmp_path), name="my-eval")
        content = (tmp_path / ".orca" / "evals" / "my-eval" / "eval-flow.yml").read_text()
        assert "setup:" not in content
        assert "assert:" in content
        assert "TODO" in content

    def test_input_md_has_frontmatter(self, tmp_path: Path) -> None:
        scaffold_eval(repo_root=_init_git_repo(tmp_path), name="my-eval")
        content = (tmp_path / ".orca" / "evals" / "my-eval" / "input.md").read_text()
        assert content.startswith("---")

    def test_assertions_md_has_criteria_section(self, tmp_path: Path) -> None:
        scaffold_eval(repo_root=_init_git_repo(tmp_path), name="my-eval")
        content = (tmp_path / ".orca" / "evals" / "my-eval" / "assertions.md").read_text()
        assert "## Criteria" in content
        assert "### " in content

    def test_refuses_existing_eval_directory(self, tmp_path: Path) -> None:
        scaffold_eval(repo_root=_init_git_repo(tmp_path), name="my-eval")
        with pytest.raises(FileExistsError):
            scaffold_eval(repo_root=tmp_path, name="my-eval")

    def test_scaffold_creates_state_branch_and_worktree(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        scaffold_eval(repo_root=repo, name="my-eval")

        rc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "orca-eval-state/my-eval"],
            capture_output=True,
        ).returncode
        assert rc == 0
        assert (repo / ".orca-state" / "eval-states" / "my-eval").is_dir()

    def test_input_md_carries_state_ref(self, tmp_path: Path) -> None:
        scaffold_eval(repo_root=_init_git_repo(tmp_path), name="my-eval")
        content = (tmp_path / ".orca" / "evals" / "my-eval" / "input.md").read_text()
        assert "state_ref: orca-eval-state/my-eval" in content
        assert "TODO_STATE_REF" not in content

    def test_validates_name_is_kebab_case(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            scaffold_eval(repo_root=tmp_path, name="My Test")
        with pytest.raises(ValueError, match="kebab-case"):
            scaffold_eval(repo_root=tmp_path, name="my_test")
        with pytest.raises(ValueError, match="kebab-case"):
            scaffold_eval(repo_root=tmp_path, name="-leading-hyphen")


class TestListEvals:
    def test_empty_when_no_evals_dir(self, tmp_path: Path) -> None:
        result = list_evals(repo_root=tmp_path)
        assert result == []

    def test_returns_eval_names_sorted(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        scaffold_eval(repo, "zebra")
        scaffold_eval(repo, "apple")
        result = list_evals(repo_root=repo)
        assert result == ["apple", "zebra"]

    def test_only_includes_directories_with_eval_flow_yml(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        scaffold_eval(repo, "valid")
        (repo / ".orca" / "evals" / "stray").mkdir()
        result = list_evals(repo_root=repo)
        assert result == ["valid"]


class TestCreateStateBranchAndWorktree:
    def test_creates_orphan_branch(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        _create_state_branch_and_worktree(repo, "my-eval")

        rc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "orca-eval-state/my-eval"],
            capture_output=True,
        ).returncode
        assert rc == 0

    def test_creates_persistent_worktree(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        _create_state_branch_and_worktree(repo, "my-eval")
        wt = repo / ".orca-state" / "eval-states" / "my-eval"
        assert wt.is_dir()
        head = subprocess.run(
            ["git", "-C", str(wt), "branch", "--show-current"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert head == "orca-eval-state/my-eval"

    def test_branch_is_orphan(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        _create_state_branch_and_worktree(repo, "my-eval")
        wt = repo / ".orca-state" / "eval-states" / "my-eval"
        assert not (wt / "README.md").exists()

    def test_does_not_change_main_repo_head(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        original_head = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        _create_state_branch_and_worktree(repo, "my-eval")
        new_head = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert new_head == original_head

    def test_errors_if_branch_already_exists(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        subprocess.run(
            ["git", "-C", str(repo), "branch", "orca-eval-state/my-eval"],
            check=True,
            capture_output=True,
        )
        with pytest.raises(FileExistsError, match="orca-eval-state/my-eval"):
            _create_state_branch_and_worktree(repo, "my-eval")


class TestParseStateRef:
    def test_returns_state_ref_value(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import parse_state_ref

        f = tmp_path / "input.md"
        f.write_text("---\ntitle: Foo\nstate_ref: orca-eval-state/foo\n---\n\n# body\n")
        assert parse_state_ref(f) == "orca-eval-state/foo"

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import parse_state_ref

        f = tmp_path / "input.md"
        f.write_text("---\ntitle: Foo\n---\n\n# body\n")
        assert parse_state_ref(f) is None

    def test_returns_none_for_placeholder(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import parse_state_ref

        f = tmp_path / "input.md"
        f.write_text("---\ntitle: Foo\nstate_ref: TODO_STATE_REF\n---\n")
        assert parse_state_ref(f) is None


class TestRunEvalStateRef:
    def test_run_eval_errors_when_input_md_missing_state_ref(self, tmp_path: Path) -> None:
        from orca.cli.eval_cmd import run_eval

        repo = _init_git_repo(tmp_path)
        eval_dir = repo / ".orca" / "evals" / "no-marker"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval-flow.yml").write_text("initial: foo\nstates:\n  foo: {}\n")
        (eval_dir / "input.md").write_text("---\ntitle: x\n---\n")
        (eval_dir / "assertions.md").write_text("# evals\n")

        with pytest.raises(RuntimeError, match="state_ref"):
            run_eval(repo, "no-marker")


class TestResolveEvalPaths:
    def test_resolves_paths_for_existing_eval(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        scaffold_eval(repo, "my-eval")
        paths = resolve_eval_paths(repo_root=repo, name="my-eval")
        assert paths.config_path == (repo / ".orca" / "evals" / "my-eval" / "eval-flow.yml").resolve()
        assert paths.task_file == (repo / ".orca" / "evals" / "my-eval" / "input.md").resolve()

    def test_raises_for_missing_eval(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            resolve_eval_paths(repo_root=tmp_path, name="ghost")


class TestScaffoldHasReviewState:
    """Scaffold must include a `review` HITL state after `assert`."""

    def test_review_state_present_and_wired(self) -> None:
        """The scaffold is intentionally incomplete (initial: TODO_BODY_STATE)
        so orca's strict parser rejects it; we inspect the YAML directly.

        YAML 1.1 parses the bare key `on` as boolean True; orca's runtime
        config parser normalizes that (config.py:158). For test purposes we
        do the same normalization here.
        """
        import yaml

        from orca.cli.eval_cmd import _SKELETON_EVAL_FLOW

        cfg = yaml.safe_load(_SKELETON_EVAL_FLOW)
        states = cfg["states"]

        def _on(state: dict[Any, Any]) -> dict[str, Any]:
            return state.get(True) or state.get("on") or {}

        assert "review" in states

        assert_on = _on(states["assert"])
        for outcome in ("passed", "failed", "inconclusive"):
            assert assert_on[outcome] == "review", (
                f"assert.{outcome} should route to review, got {assert_on[outcome]!r}"
            )

        review = states["review"]
        assert review["worker"]["kind"] == "claude-code"

        outcome_values = review["worker"]["result_format"]["outcome"]["values"]
        assert "reviewed" in outcome_values
        assert "skipped" in outcome_values

        review_on = _on(review)
        assert review_on["reviewed"] == "done"
        assert review_on["skipped"] == "done"
