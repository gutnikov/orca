from orca.engine.types import (
    DebugReviewSnapshot,
    DiffFile,
    Hunk,
    InlineComment,
)


def test_inline_comment_round_trip() -> None:
    comment = InlineComment(
        id="c1",
        file="src/auth.ts",
        line=42,
        body="use Result type",
        created_at="2026-05-25T10:00:00+00:00",
        updated_at="2026-05-25T10:00:00+00:00",
    )
    d = comment.to_dict()
    assert d == {
        "id": "c1",
        "file": "src/auth.ts",
        "line": 42,
        "body": "use Result type",
        "created_at": "2026-05-25T10:00:00+00:00",
        "updated_at": "2026-05-25T10:00:00+00:00",
    }
    assert InlineComment.from_dict(d) == comment


def test_inline_comment_allows_file_level_anchor() -> None:
    comment = InlineComment(
        id="c2",
        file="prompt.md",
        line=None,
        body="general feedback",
        created_at="2026-05-25T10:00:00+00:00",
        updated_at="2026-05-25T10:00:00+00:00",
    )
    d = comment.to_dict()
    assert d["line"] is None
    assert InlineComment.from_dict(d) == comment


def test_hunk_round_trip() -> None:
    hunk = Hunk(
        old_start=10,
        old_lines=3,
        new_start=10,
        new_lines=5,
        lines=[" context", "+added", "-removed"],
    )
    assert Hunk.from_dict(hunk.to_dict()) == hunk


def test_diff_file_round_trip() -> None:
    diff = DiffFile(
        path="src/auth.ts",
        status="modified",
        hunks=[Hunk(1, 0, 1, 1, ["+new"])],
    )
    assert DiffFile.from_dict(diff.to_dict()) == diff


def test_debug_review_snapshot_round_trip() -> None:
    snapshot = DebugReviewSnapshot(
        rendered_prompt="# Implement auth",
        worker_result={"outcome": "done"},
        config_slice="states:\n  implementing:\n    worker: ...",
        diff_files=[DiffFile("src/a.ts", "modified", [])],
        base_commit="abc123",
    )
    d = snapshot.to_dict()
    assert d["base_commit"] == "abc123"
    assert DebugReviewSnapshot.from_dict(d) == snapshot
