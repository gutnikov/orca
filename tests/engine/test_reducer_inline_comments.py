"""Reducer tests for InlineComment + CommentThread events."""

from orca.engine.reducer import reduce
from orca.engine.types import (
    CommentThreadMessageAddedEvent,
    CommentThreadReviewedEvent,
    DebugDecisionEvent,
    InlineCommentDeletedEvent,
    InlineCommentSavedEvent,
    Issue,
    State,
    StateMachineConfig,
    TypeDef,
)


def _make_state() -> State:
    issue = Issue(
        type="t",
        fields={},
        state="s",
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
    )
    return State(issues={"i1": issue}, worker_queues={})


def _config() -> StateMachineConfig:
    return StateMachineConfig(
        root_type="t",
        types={"t": TypeDef(fields={}, initial="s", states={})},
    )


def _ts() -> str:
    return "2026-05-25T10:00:00+00:00"


def _now() -> str:
    return _ts()


def _gen_id() -> str:
    return "fixed-id"


def test_inline_comment_saved_creates_record() -> None:
    state = _make_state()
    event = InlineCommentSavedEvent(
        issue_id="i1",
        comment_id="c1",
        file="src/foo.ts",
        line=42,
        body="hello",
        timestamp=_ts(),
    )
    new_state, effects = reduce(_config(), state, event, _gen_id, _now)
    comments = new_state.issues["i1"].inline_comments
    assert len(comments) == 1
    assert comments[0].id == "c1"
    assert comments[0].body == "hello"
    assert effects == []


def test_inline_comment_saved_updates_existing_in_place() -> None:
    state = _make_state()
    initial = InlineCommentSavedEvent(
        issue_id="i1",
        comment_id="c1",
        file="f",
        line=1,
        body="v1",
        timestamp=_ts(),
    )
    state, _ = reduce(_config(), state, initial, _gen_id, _now)
    update = InlineCommentSavedEvent(
        issue_id="i1",
        comment_id="c1",
        file="f",
        line=1,
        body="v2",
        timestamp="2026-05-25T11:00:00+00:00",
    )
    state, _ = reduce(_config(), state, update, _gen_id, _now)
    comments = state.issues["i1"].inline_comments
    assert len(comments) == 1
    assert comments[0].body == "v2"
    assert comments[0].updated_at == "2026-05-25T11:00:00+00:00"


def test_inline_comment_deleted_removes_record_and_thread() -> None:
    state = _make_state()
    state, _ = reduce(
        _config(),
        state,
        InlineCommentSavedEvent(issue_id="i1", comment_id="c1", file="f", line=1, body="b", timestamp=_ts()),
        _gen_id,
        _now,
    )
    state, _ = reduce(
        _config(),
        state,
        CommentThreadMessageAddedEvent(
            issue_id="i1", comment_id="c1", role="agent", message_id="m1", body="hi", timestamp=_ts()
        ),
        _gen_id,
        _now,
    )
    assert len(state.issues["i1"].comment_threads) == 1

    state, _ = reduce(
        _config(), state, InlineCommentDeletedEvent(issue_id="i1", comment_id="c1", timestamp=_ts()), _gen_id, _now
    )
    assert state.issues["i1"].inline_comments == []
    assert state.issues["i1"].comment_threads == []


def test_thread_message_added_creates_thread_lazily() -> None:
    state = _make_state()
    state, _ = reduce(
        _config(),
        state,
        InlineCommentSavedEvent(issue_id="i1", comment_id="c1", file="f", line=1, body="b", timestamp=_ts()),
        _gen_id,
        _now,
    )
    event = CommentThreadMessageAddedEvent(
        issue_id="i1",
        comment_id="c1",
        role="agent",
        message_id="m1",
        body="reply",
        timestamp=_ts(),
    )
    state, _ = reduce(_config(), state, event, _gen_id, _now)
    threads = state.issues["i1"].comment_threads
    assert len(threads) == 1
    assert threads[0].comment_id == "c1"
    assert len(threads[0].messages) == 1
    assert threads[0].messages[0].body == "reply"
    # Agent message bumps agent_last_reviewed_at
    assert threads[0].agent_last_reviewed_at == _ts()


def test_user_thread_message_does_not_bump_agent_reviewed_at() -> None:
    state = _make_state()
    state, _ = reduce(
        _config(),
        state,
        InlineCommentSavedEvent(issue_id="i1", comment_id="c1", file="f", line=1, body="b", timestamp=_ts()),
        _gen_id,
        _now,
    )
    state, _ = reduce(
        _config(),
        state,
        CommentThreadMessageAddedEvent(
            issue_id="i1",
            comment_id="c1",
            role="agent",
            message_id="m1",
            body="r1",
            timestamp="2026-05-25T10:00:00+00:00",
        ),
        _gen_id,
        _now,
    )
    state, _ = reduce(
        _config(),
        state,
        CommentThreadMessageAddedEvent(
            issue_id="i1",
            comment_id="c1",
            role="user",
            message_id="m2",
            body="r2",
            timestamp="2026-05-25T11:00:00+00:00",
        ),
        _gen_id,
        _now,
    )
    thread = state.issues["i1"].comment_threads[0]
    # Agent reviewed-at should still be the first agent message timestamp, not bumped by the user reply
    assert thread.agent_last_reviewed_at == "2026-05-25T10:00:00+00:00"


def test_thread_reviewed_bumps_agent_last_reviewed_at() -> None:
    state = _make_state()
    state, _ = reduce(
        _config(),
        state,
        InlineCommentSavedEvent(issue_id="i1", comment_id="c1", file="f", line=1, body="b", timestamp=_ts()),
        _gen_id,
        _now,
    )
    review_ts = "2026-05-25T12:00:00+00:00"
    state, _ = reduce(
        _config(),
        state,
        CommentThreadReviewedEvent(
            issue_id="i1",
            comment_id="c1",
            timestamp=review_ts,
            reason="not actionable",
        ),
        _gen_id,
        _now,
    )
    threads = state.issues["i1"].comment_threads
    # Skip lazily creates a thread with empty messages
    assert len(threads) == 1
    assert threads[0].messages == []
    assert threads[0].agent_last_reviewed_at == review_ts


def test_inline_comment_and_threads_cleared_on_decision() -> None:
    state = _make_state()
    state, _ = reduce(
        _config(),
        state,
        InlineCommentSavedEvent(issue_id="i1", comment_id="c1", file="f", line=1, body="b", timestamp=_ts()),
        _gen_id,
        _now,
    )
    state, _ = reduce(
        _config(),
        state,
        CommentThreadMessageAddedEvent(
            issue_id="i1", comment_id="c1", role="agent", message_id="m1", body="r", timestamp=_ts()
        ),
        _gen_id,
        _now,
    )
    # Pretend issue is in debug-pending state for the decision to proceed
    state.issues["i1"].debug_pending = True

    decision = DebugDecisionEvent(
        issue_id="i1",
        action="accept",
        comments=[],
        timestamp=_ts(),
    )
    state, _ = reduce(_config(), state, decision, _gen_id, _now)
    assert state.issues["i1"].inline_comments == []
    assert state.issues["i1"].comment_threads == []
