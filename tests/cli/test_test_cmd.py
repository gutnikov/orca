from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orca.cli.test_cmd import (
    list_tests,
    resolve_test_paths,
    scaffold_test,
)


def _init_git_repo(path: Path) -> Path:
    """Initialise a minimal git repo so scaffold_test can create branches."""
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


class TestScaffoldTest:
    def test_creates_test_directory(self, tmp_path: Path) -> None:
        scaffold_test(repo_root=_init_git_repo(tmp_path), name="my-test")
        assert (tmp_path / ".orca" / "tests" / "my-test").is_dir()

    def test_creates_required_files(self, tmp_path: Path) -> None:
        scaffold_test(repo_root=_init_git_repo(tmp_path), name="my-test")
        test_dir = tmp_path / ".orca" / "tests" / "my-test"
        assert (test_dir / "test-flow.yml").exists()
        assert (test_dir / "input.md").exists()
        assert (test_dir / "evaluations.md").exists()
        assert not (test_dir / "fixtures").exists()

    def test_test_flow_yml_is_skeleton(self, tmp_path: Path) -> None:
        scaffold_test(repo_root=_init_git_repo(tmp_path), name="my-test")
        content = (tmp_path / ".orca" / "tests" / "my-test" / "test-flow.yml").read_text()
        assert "setup:" not in content
        assert "evaluate:" in content
        assert "TODO" in content

    def test_input_md_has_frontmatter(self, tmp_path: Path) -> None:
        scaffold_test(repo_root=_init_git_repo(tmp_path), name="my-test")
        content = (tmp_path / ".orca" / "tests" / "my-test" / "input.md").read_text()
        assert content.startswith("---")

    def test_evaluations_md_has_criteria_section(self, tmp_path: Path) -> None:
        scaffold_test(repo_root=_init_git_repo(tmp_path), name="my-test")
        content = (tmp_path / ".orca" / "tests" / "my-test" / "evaluations.md").read_text()
        assert "## Criteria" in content
        assert "### " in content

    def test_refuses_existing_test_directory(self, tmp_path: Path) -> None:
        scaffold_test(repo_root=_init_git_repo(tmp_path), name="my-test")
        with pytest.raises(FileExistsError):
            scaffold_test(repo_root=tmp_path, name="my-test")

    def test_input_md_carries_state_ref(self, tmp_path: Path) -> None:
        scaffold_test(repo_root=_init_git_repo(tmp_path), name="my-test")
        content = (tmp_path / ".orca" / "tests" / "my-test" / "input.md").read_text()
        assert "state_ref: orca-test-state/my-test" in content
        assert "TODO_STATE_REF" not in content

    def test_validates_name_is_kebab_case(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            scaffold_test(repo_root=tmp_path, name="My Test")
        with pytest.raises(ValueError, match="kebab-case"):
            scaffold_test(repo_root=tmp_path, name="my_test")
        with pytest.raises(ValueError, match="kebab-case"):
            scaffold_test(repo_root=tmp_path, name="-leading-hyphen")


class TestListTests:
    def test_empty_when_no_tests_dir(self, tmp_path: Path) -> None:
        result = list_tests(repo_root=tmp_path)
        assert result == []

    def test_returns_test_names_sorted(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        scaffold_test(repo, "zebra")
        scaffold_test(repo, "apple")
        result = list_tests(repo_root=repo)
        assert result == ["apple", "zebra"]

    def test_only_includes_directories_with_test_flow_yml(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        scaffold_test(repo, "valid")
        (repo / ".orca" / "tests" / "stray").mkdir()
        result = list_tests(repo_root=repo)
        assert result == ["valid"]


class TestCreateStateBranchAndWorktree:
    def test_creates_orphan_branch(self, tmp_path: Path) -> None:
        from orca.cli.test_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        _create_state_branch_and_worktree(repo, "my-test")

        rc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "orca-test-state/my-test"],
            capture_output=True,
        ).returncode
        assert rc == 0

    def test_creates_persistent_worktree(self, tmp_path: Path) -> None:
        from orca.cli.test_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        _create_state_branch_and_worktree(repo, "my-test")
        wt = repo / ".orca-state" / "test-states" / "my-test"
        assert wt.is_dir()
        head = subprocess.run(
            ["git", "-C", str(wt), "branch", "--show-current"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert head == "orca-test-state/my-test"

    def test_branch_is_orphan(self, tmp_path: Path) -> None:
        from orca.cli.test_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        _create_state_branch_and_worktree(repo, "my-test")
        wt = repo / ".orca-state" / "test-states" / "my-test"
        assert not (wt / "README.md").exists()

    def test_does_not_change_main_repo_head(self, tmp_path: Path) -> None:
        from orca.cli.test_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        original_head = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        _create_state_branch_and_worktree(repo, "my-test")
        new_head = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert new_head == original_head

    def test_errors_if_branch_already_exists(self, tmp_path: Path) -> None:
        from orca.cli.test_cmd import _create_state_branch_and_worktree

        repo = _init_git_repo(tmp_path)
        subprocess.run(
            ["git", "-C", str(repo), "branch", "orca-test-state/my-test"],
            check=True,
            capture_output=True,
        )
        with pytest.raises(FileExistsError, match="orca-test-state/my-test"):
            _create_state_branch_and_worktree(repo, "my-test")


class TestResolveTestPaths:
    def test_resolves_paths_for_existing_test(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        scaffold_test(repo, "my-test")
        paths = resolve_test_paths(repo_root=repo, name="my-test")
        assert paths.config_path == (repo / ".orca" / "tests" / "my-test" / "test-flow.yml").resolve()
        assert paths.task_file == (repo / ".orca" / "tests" / "my-test" / "input.md").resolve()

    def test_raises_for_missing_test(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            resolve_test_paths(repo_root=tmp_path, name="ghost")
