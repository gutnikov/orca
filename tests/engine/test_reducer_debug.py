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


def test_debug_decision_modify_continue_advances_state_and_marks_modify_pending() -> None:
    """modify_continue = accept (advance state) + modify_pending=True.

    The user's intent: keep this output, but update the prompt/config from my
    comments for future runs. So the state transitions like accept, but the
    issue ends with modify_pending=True so the host skill picks up the
    rewrite work.
    """
    from orca.engine.types import DebugDecisionEvent, EventLogEntry, InlineComment

    config = _make_config()
    state = _make_state(worker_active=False)
    issue = state.issues["i1"]
    issue.debug_pending = True
    issue.event_log.append(EventLogEntry(timestamp="t0", type="worker_result", data={"outcome": "done"}))

    comments = [
        InlineComment(
            id="c1",
            file="prompt.md",
            line=None,
            body="add a step about retries",
            created_at="t1",
            updated_at="t1",
        )
    ]
    event = DebugDecisionEvent(issue_id="i1", action="modify_continue", comments=comments, timestamp="t1")
    new_state, _ = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")

    new_issue = new_state.issues["i1"]
    # State advanced (per accept logic)
    assert new_issue.state == "done"
    # ...but the modify_pending flag is set so the skill knows to rewrite
    assert new_issue.modify_pending is True
    assert new_issue.debug_pending is False
    # The comments were captured in a debug_modify_request event the way
    # orca-prompt-config-rewrite expects to find them.
    modify_events = [e for e in new_issue.event_log if e.type == "debug_modify_request"]
    assert len(modify_events) == 1
    assert modify_events[0].data["comments"][0]["body"] == "add a step about retries"


def test_debug_decision_modify_continue_without_worker_result_errors() -> None:
    """No accept means no worker_result — surface an ErrorEffect."""
    from orca.engine.types import DebugDecisionEvent, ErrorEffect

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True  # no worker_result in log

    event = DebugDecisionEvent(issue_id="i1", action="modify_continue", comments=[], timestamp="t1")
    _, effects = reduce(config, state, event, generate_id=lambda: "id", now=lambda: "now")
    assert any(isinstance(e, ErrorEffect) for e in effects)


def test_debug_decision_modify_restart_marks_modify_pending_and_logs_request() -> None:
    from orca.engine.types import DebugDecisionEvent, InlineComment

    config = _make_config()
    state = _make_state(worker_active=False)
    state.issues["i1"].debug_pending = True

    comments = [
        InlineComment(
            id="c1",
            file="prompt.md",
            line=None,
            body="use Result type",
            created_at="t1",
            updated_at="t1",
        )
    ]
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
        InlineComment(
            id="c1",
            file="prompt.md",
            line=12,
            body="use Result type",
            created_at="t1",
            updated_at="t1",
        ),
        InlineComment(
            id="c2",
            file="result.json",
            line=3,
            body="this enum should also include 'partial'",
            created_at="t1",
            updated_at="t1",
        ),
        InlineComment(
            id="c3",
            file="__overall__",
            line=None,
            body="prefer concise prompts; trim the recap block",
            created_at="t1",
            updated_at="t1",
        ),
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
