from orca.engine.types import (
    DebugDecisionEvent,
    DebugModifyRequestEvent,
    DebugReviewRequiredEvent,
    DebugReviewSnapshot,
    Event,
    InlineComment,
)


def test_debug_review_required_event_is_an_event() -> None:
    snapshot = DebugReviewSnapshot(
        rendered_prompt="",
        worker_result={},
        config_slice="",
        diff_files=[],
        base_commit="abc",
    )
    event: Event = DebugReviewRequiredEvent(
        issue_id="x",
        snapshot=snapshot,
        timestamp="2026-05-23T00:00:00Z",
    )
    assert isinstance(event, DebugReviewRequiredEvent)


def _make_comment() -> InlineComment:
    return InlineComment(
        id="c1",
        file="prompt.md",
        line=None,
        body="note",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
    )


def test_debug_decision_event_is_an_event() -> None:
    event: Event = DebugDecisionEvent(
        issue_id="x",
        action="accept",
        comments=[_make_comment()],
        timestamp="2026-05-23T00:00:00Z",
    )
    assert isinstance(event, DebugDecisionEvent)
    assert event.action == "accept"
    assert len(event.comments) == 1


def test_debug_modify_request_event_is_an_event() -> None:
    event: Event = DebugModifyRequestEvent(
        issue_id="x",
        comments=[_make_comment()],
        timestamp="2026-05-23T00:00:00Z",
    )
    assert isinstance(event, DebugModifyRequestEvent)


def test_all_four_actions_construct_successfully() -> None:
    for action in ("accept", "restart", "modify_restart", "stop"):
        DebugDecisionEvent(issue_id="x", action=action, comments=[], timestamp="t")
