from orca.engine.types import Issue


def test_issue_has_debug_state_fields_with_defaults() -> None:
    issue = Issue(
        type="task",
        fields={},
        state="initial",
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
    )
    assert issue.state_base_commit is None
    assert issue.debug_pending is False
    assert issue.modify_pending is False
    assert issue.agent_surfaced_at is None


def test_issue_round_trip_preserves_debug_fields() -> None:
    issue = Issue(
        type="task",
        fields={},
        state="implementing",
        worker_active=True,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
        state_base_commit="abc123",
        debug_pending=True,
        modify_pending=False,
        agent_surfaced_at=1234567890.0,
    )
    round_tripped = Issue.from_dict(issue.to_dict())
    assert round_tripped.state_base_commit == "abc123"
    assert round_tripped.debug_pending is True
    assert round_tripped.modify_pending is False
    assert round_tripped.agent_surfaced_at == 1234567890.0


def test_issue_from_dict_defaults_missing_debug_fields() -> None:
    """Existing serialized issues (pre-debug-mode) must still load."""
    legacy = {
        "type": "task",
        "fields": {},
        "state": "initial",
        "worker_active": False,
        "decomposed_from": None,
        "depends_on": [],
        "event_log": [],
    }
    issue = Issue.from_dict(legacy)
    assert issue.state_base_commit is None
    assert issue.debug_pending is False
    assert issue.modify_pending is False
    assert issue.agent_surfaced_at is None
