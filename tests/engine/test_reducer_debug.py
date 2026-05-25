from orca.engine.reducer import reduce
from orca.engine.types import (
    DebugReviewRequiredEvent,
    Issue,
    OnTransition,
    State,
    StateDef,
    StateMachineConfig,
    TypeDef,
    WorkerDef,
    WorkerResultEvent,
)


def _make_config() -> StateMachineConfig:
    return StateMachineConfig(
        root_type="task",
        types={
            "task": TypeDef(
                fields={},
                initial="implementing",
                states={
                    "implementing": StateDef(
                        worker=WorkerDef(
                            kind="claude-code",
                            prompt="p.md",
                            result_format={},
                        ),
                        on={"done": OnTransition(target="done")},
                    ),
                },
            )
        },
    )


def _make_state(worker_active: bool = True) -> State:
    issue = Issue(
        type="task",
        fields={},
        state="implementing",
        worker_active=worker_active,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
    )
    return State(issues={"i1": issue}, worker_queues={})


def test_worker_result_in_debug_mode_pauses_instead_of_transitioning() -> None:
    config = _make_config()
    state = _make_state()
    event = WorkerResultEvent(issue_id="i1", result={"outcome": "done"}, timestamp="t1")

    new_state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now", run_debug=True)

    issue = new_state.issues["i1"]
    assert issue.state == "implementing"  # NOT transitioned
    assert issue.debug_pending is True
    assert any(e.type == "worker_result" for e in issue.event_log)


def test_worker_result_in_non_debug_mode_transitions_normally() -> None:
    config = _make_config()
    state = _make_state()
    event = WorkerResultEvent(issue_id="i1", result={"outcome": "done"}, timestamp="t1")

    new_state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now", run_debug=False)

    issue = new_state.issues["i1"]
    assert issue.state == "done"
    assert issue.debug_pending is False


def test_debug_review_required_event_appends_log_entry() -> None:
    from orca.engine.types import DebugReviewSnapshot

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True
    snapshot = DebugReviewSnapshot(
        rendered_prompt="prompt",
        worker_result={"outcome": "done"},
        config_slice="",
        diff_files=[],
        base_commit="abc",
    )
    event = DebugReviewRequiredEvent(issue_id="i1", snapshot=snapshot, timestamp="t1")

    new_state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    entries = [e for e in new_state.issues["i1"].event_log if e.type == "debug_review_required"]
    assert len(entries) == 1
    assert entries[0].data["snapshot"]["base_commit"] == "abc"


def test_debug_decision_accept_applies_transition() -> None:
    config = _make_config()
    state = _make_state(worker_active=False)
    issue = state.issues["i1"]
    issue.debug_pending = True
    from orca.engine.types import EventLogEntry

    issue.event_log.append(EventLogEntry(timestamp="t0", type="worker_result", data={"outcome": "done"}))

    from orca.engine.types import DebugDecisionEvent

    event = DebugDecisionEvent(issue_id="i1", action="accept", comments=[], timestamp="t1")
    new_state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    assert new_state.issues["i1"].state == "done"
    assert new_state.issues["i1"].debug_pending is False


def test_debug_decision_restart_emits_dispatch_effect() -> None:
    from orca.engine.types import DebugDecisionEvent, DispatchWorkerEffect

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    event = DebugDecisionEvent(issue_id="i1", action="restart", comments=[], timestamp="t1")
    new_state, effects = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    assert new_state.issues["i1"].state == "implementing"
    assert new_state.issues["i1"].debug_pending is False
    assert new_state.issues["i1"].worker_active is True
    assert any(isinstance(e, DispatchWorkerEffect) and e.issue_id == "i1" for e in effects)


def test_debug_decision_modify_restart_marks_modify_pending_and_logs_request() -> None:
    from orca.engine.types import DebugDecisionEvent, InlineComment

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    comments = [InlineComment(file="prompt.md", line=None, body="use Result type")]
    event = DebugDecisionEvent(issue_id="i1", action="modify_restart", comments=comments, timestamp="t1")
    new_state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    issue = new_state.issues["i1"]
    assert issue.modify_pending is True
    assert issue.debug_pending is False
    assert issue.worker_active is False
    assert any(e.type == "debug_modify_request" for e in issue.event_log)


def test_modify_restart_preserves_overall_feedback_and_line_comments() -> None:
    """Regression for the route handler dropping the __overall__ payload.

    The web UI bundles the overall-feedback textarea into the comments array
    as a single entry with file='__overall__' and line=None. The orca-prompt-
    config-rewrite SKILL relies on this entry surviving the round-trip into
    the debug_modify_request event log so the meta-agent can use general
    direction alongside line-anchored comments.
    """
    from orca.engine.types import DebugDecisionEvent, InlineComment

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    comments = [
        InlineComment(file="prompt.md", line=12, body="use Result type"),
        InlineComment(file="result.json", line=3, body="this enum should also include 'partial'"),
        InlineComment(file="__overall__", line=None, body="prefer concise prompts; trim the recap block"),
    ]
    event = DebugDecisionEvent(issue_id="i1", action="modify_restart", comments=comments, timestamp="t1")
    new_state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    issue = new_state.issues["i1"]
    request_entries = [e for e in issue.event_log if e.type == "debug_modify_request"]
    assert len(request_entries) == 1
    logged_comments = request_entries[0].data["comments"]
    assert len(logged_comments) == 3
    overall = next((c for c in logged_comments if c["file"] == "__overall__"), None)
    assert overall is not None, "overall feedback was not logged"
    assert overall["line"] is None
    assert overall["body"] == "prefer concise prompts; trim the recap block"
    # Line comments are also intact, with their file/line/body preserved
    line_files = {c["file"] for c in logged_comments if c["line"] is not None}
    assert line_files == {"prompt.md", "result.json"}


def test_debug_decision_stop_clears_pending_and_emits_no_effects() -> None:
    from orca.engine.types import DebugDecisionEvent, DispatchWorkerEffect

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    event = DebugDecisionEvent(issue_id="i1", action="stop", comments=[], timestamp="t1")
    new_state, effects = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    assert new_state.issues["i1"].debug_pending is False
    assert not any(isinstance(e, DispatchWorkerEffect) for e in effects)


def test_debug_decision_rejects_unknown_action_with_error_effect() -> None:
    from orca.engine.types import DebugDecisionEvent, ErrorEffect

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    event = DebugDecisionEvent(issue_id="i1", action="weird", comments=[], timestamp="t1")
    _, effects = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    assert any(isinstance(e, ErrorEffect) for e in effects)


def test_debug_question_asked_appends_to_issue_and_logs_event() -> None:
    from orca.engine.types import DebugQuestionAskedEvent

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    event = DebugQuestionAskedEvent(
        issue_id="i1",
        question_id="q1",
        client_comment_id="c-abc",
        file="tests/foo.spec.ts",
        line=42,
        body="why broken?",
        timestamp="t1",
    )
    new_state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    questions = new_state.issues["i1"].debug_questions
    assert len(questions) == 1
    assert questions[0].id == "q1"
    assert questions[0].client_comment_id == "c-abc"
    assert questions[0].file == "tests/foo.spec.ts"
    assert questions[0].line == 42
    assert questions[0].body == "why broken?"
    assert questions[0].answer is None
    assert new_state.issues["i1"].event_log[-1].type == "debug_question_asked"


def test_debug_question_asked_is_idempotent_on_question_id() -> None:
    from orca.engine.types import DebugQuestionAskedEvent

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    event = DebugQuestionAskedEvent(
        issue_id="i1",
        question_id="q1",
        client_comment_id="c-abc",
        file="f.ts",
        line=1,
        body="?",
        timestamp="t1",
    )
    state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")
    state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")
    assert len(state.issues["i1"].debug_questions) == 1


def test_debug_question_answered_attaches_answer_and_logs() -> None:
    from orca.engine.types import DebugQuestionAnsweredEvent, DebugQuestionAskedEvent

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    ask = DebugQuestionAskedEvent(
        issue_id="i1",
        question_id="q1",
        client_comment_id="c-abc",
        file="f.ts",
        line=1,
        body="why?",
        timestamp="t1",
    )
    state, _ = reduce(config, state, ask, generate_id=lambda: "id", now=lambda: "now")

    answer = DebugQuestionAnsweredEvent(
        issue_id="i1",
        question_id="q1",
        answer="Because the spec hasn't been written yet.",
        timestamp="t2",
    )
    new_state, _ = reduce(config, state, answer, generate_id=lambda: "id", now=lambda: "now")

    questions = new_state.issues["i1"].debug_questions
    assert questions[0].answer == "Because the spec hasn't been written yet."
    assert new_state.issues["i1"].event_log[-1].type == "debug_question_answered"


def test_debug_question_answered_with_unknown_id_emits_error_effect() -> None:
    from orca.engine.types import DebugQuestionAnsweredEvent, ErrorEffect

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    answer = DebugQuestionAnsweredEvent(
        issue_id="i1",
        question_id="does-not-exist",
        answer="ok",
        timestamp="t1",
    )
    _, effects = reduce(config, state, answer, generate_id=lambda: "id", now=lambda: "now")
    assert any(isinstance(e, ErrorEffect) for e in effects)


def test_debug_decision_clears_questions() -> None:
    """Questions are ephemeral aids for the current pause — drop on decision."""
    from orca.engine.types import DebugDecisionEvent, DebugQuestionAskedEvent

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    state, _ = reduce(
        config,
        state,
        DebugQuestionAskedEvent(
            issue_id="i1",
            question_id="q1",
            client_comment_id="c1",
            file="f.ts",
            line=1,
            body="?",
            timestamp="t1",
        ),
        generate_id=lambda: "id",
        now=lambda: "now",
    )
    assert len(state.issues["i1"].debug_questions) == 1

    # modify_restart leaves the issue paused but should still clear questions.
    state, _ = reduce(
        config,
        state,
        DebugDecisionEvent(issue_id="i1", action="modify_restart", comments=[], timestamp="t2"),
        generate_id=lambda: "id",
        now=lambda: "now",
    )
    assert state.issues["i1"].debug_questions == []
