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
