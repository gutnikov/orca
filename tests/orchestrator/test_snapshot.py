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


def test_parse_unified_diff_captures_raw_text_and_counters() -> None:
    """Each DiffFile gets its own raw diff-text slice + addition/deletion counters.

    Without these the web UI's DiffView re-parses an empty string and shows
    'diff not available' — exactly the bug the user hit on a newly-added file.
    """
    diff = """diff --git a/new.md b/new.md
new file mode 100644
index 0000000..abc
--- /dev/null
+++ b/new.md
@@ -0,0 +1,3 @@
+# Title
+
+Body
diff --git a/edited.py b/edited.py
index aaa..bbb 100644
--- a/edited.py
+++ b/edited.py
@@ -1,3 +1,3 @@
 line1
-old line
+new line
 line3
"""
    files = parse_unified_diff(diff)
    assert len(files) == 2

    added = files[0]
    assert added.path == "new.md"
    assert added.status == "added"
    assert added.additions == 3
    assert added.deletions == 0
    assert "diff --git a/new.md b/new.md" in added.raw_diff
    assert "+# Title" in added.raw_diff
    assert "edited.py" not in added.raw_diff

    edited = files[1]
    assert edited.path == "edited.py"
    assert edited.status == "modified"
    assert edited.additions == 1
    assert edited.deletions == 1
    assert "diff --git a/edited.py b/edited.py" in edited.raw_diff
    assert "new.md" not in edited.raw_diff


def test_diff_file_round_trip_preserves_raw_diff() -> None:
    """to_dict / from_dict carry the raw diff text and counters."""
    from orca.engine.types import DiffFile, Hunk

    f = DiffFile(
        path="x.py",
        status="modified",
        hunks=[Hunk(1, 1, 1, 1, [" a", "-b", "+c"])],
        raw_diff="diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-b\n+c\n",
        additions=1,
        deletions=1,
    )
    f2 = DiffFile.from_dict(f.to_dict())
    assert f2.raw_diff == f.raw_diff
    assert f2.additions == 1
    assert f2.deletions == 1
