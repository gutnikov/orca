import asyncio
import subprocess
from pathlib import Path

from orca.engine.types import DebugReviewSnapshot
from orca.orchestrator.snapshot import (
    build_snapshot,
    extract_config_slice,
    parse_unified_diff,
)


def _run(cmd: list[str], cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def test_extract_config_slice_returns_state_block() -> None:
    yaml = """root_type: task
types:
  task:
    initial: implementing
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scoping.md
        on:
          done: implementing
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/implementing.md
          model: claude-sonnet-4-6
        on:
          done: done
"""
    slice_ = extract_config_slice(yaml, "task", "implementing")
    assert "implementing:" in slice_
    assert "claude-sonnet-4-6" in slice_
    assert "scoping:" not in slice_


def test_extract_config_slice_missing_state_returns_placeholder() -> None:
    yaml = "root_type: task\ntypes:\n  task:\n    initial: a\n    states:\n      a:\n        on: {}\n"
    slice_ = extract_config_slice(yaml, "task", "nonexistent")
    assert "not found" in slice_.lower()


def test_parse_unified_diff_extracts_files_and_hunks() -> None:
    diff = """diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 line1
-line2
+line2-new
+line3
 line4
"""
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert files[0].path == "foo.py"
    assert files[0].status == "modified"
    assert len(files[0].hunks) == 1
    assert files[0].hunks[0].old_start == 1


def test_parse_unified_diff_detects_added_file() -> None:
    diff = """diff --git a/new.py b/new.py
new file mode 100644
index 0000000..abc
--- /dev/null
+++ b/new.py
@@ -0,0 +1,1 @@
+hello
"""
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert files[0].status == "added"


def test_parse_unified_diff_empty_returns_empty() -> None:
    assert parse_unified_diff("") == []


def test_build_snapshot_integration(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "T"], repo)
    (repo / "a.py").write_text("hello\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-qm", "c1"], repo)
    base = _run(["git", "rev-parse", "HEAD"], repo)
    (repo / "a.py").write_text("hello\nworld\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-qm", "c2"], repo)

    rendered_prompt_path = tmp_path / "rendered-prompt.md"
    rendered_prompt_path.write_text("# Render\nBe helpful.\n")
    config_yaml = """root_type: task
types:
  task:
    initial: x
    states:
      x:
        on: {}
"""
    config_path = tmp_path / "flow.yml"
    config_path.write_text(config_yaml)

    snapshot = asyncio.run(
        build_snapshot(
            worktree_path=repo,
            base_commit=base,
            rendered_prompt_path=rendered_prompt_path,
            worker_result={"outcome": "done"},
            config_path=config_path,
            issue_type="task",
            state_id="x",
        )
    )

    assert isinstance(snapshot, DebugReviewSnapshot)
    assert snapshot.rendered_prompt == "# Render\nBe helpful.\n"
    assert snapshot.worker_result == {"outcome": "done"}
    assert "x:" in snapshot.config_slice
    assert snapshot.base_commit == base
    assert len(snapshot.diff_files) == 1
    assert snapshot.diff_files[0].path == "a.py"


def test_build_snapshot_missing_rendered_prompt_returns_empty_string(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "T"], repo)
    (repo / "f").write_text("x")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-qm", "c"], repo)
    base = _run(["git", "rev-parse", "HEAD"], repo)

    config_path = tmp_path / "flow.yml"
    config_path.write_text("root_type: t\ntypes:\n  t:\n    initial: a\n    states:\n      a:\n        on: {}\n")

    snapshot = asyncio.run(
        build_snapshot(
            worktree_path=repo,
            base_commit=base,
            rendered_prompt_path=tmp_path / "missing.md",
            worker_result={},
            config_path=config_path,
            issue_type="t",
            state_id="a",
        )
    )
    assert snapshot.rendered_prompt == ""
