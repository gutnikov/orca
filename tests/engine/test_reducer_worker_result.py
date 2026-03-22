from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    ErrorEffect,
    State,
    WorkerResultEvent,
)


def _counter() -> Callable[[], str]:
    n = 0

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"id-{n}"

    return next_id


def _clock(value: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: value


def _create_and_advance(
    config: object,
    state: State,
    issue_id: str,
    target_state: str,
    gen: Callable[[], str],
) -> State:
    from orca.engine.types import StateMachineConfig

    assert isinstance(config, StateMachineConfig)
    state, _ = reduce(
        config,
        state,
        CreateEvent(issue_id=issue_id, fields={"title": "T", "text": "D"}, timestamp="2026-01-01T00:00:00Z"),
        gen,
        _clock(),
    )
    if state.issues[issue_id].state != target_state:
        state, _ = reduce(
            config,
            state,
            AdvanceEvent(issue_id=issue_id, target_state=target_state, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
    return state


class TestSimpleTransition:
    """Test 1: implementing -> done, verify state change, event_log, worker_active=False."""

    def test_transition_to_terminal(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create issue -> lands in todo (active), worker dispatched
        state, effects = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].worker_active is True

        # Worker returns "start" -> transition to implementing
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"
        assert state.issues["A"].worker_active is True  # re-dispatched in implementing

        # Worker returns "complete" -> transition to done (terminal)
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "done"
        assert state.issues["A"].worker_active is False
        # Check event_log for worker_result entries
        result_entries = [e for e in state.issues["A"].event_log if e.type == "worker_result"]
        assert len(result_entries) == 2
        assert result_entries[0].data == {"outcome": "start"}
        assert result_entries[1].data == {"outcome": "complete"}
        # No dispatch effects for terminal state
        assert not any(isinstance(e, DispatchWorkerEffect) for e in effects)


class TestTransitionToActiveState:
    """Test 2: implementing -> testing equivalent, verify DispatchWorkerEffect."""

    def test_dispatch_on_transition_to_active(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        # todo -> implementing via "start"
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"
        # Should get a DispatchWorkerEffect for the implementing state
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1
        assert dispatch_effects[0].issue_id == "A"
        assert dispatch_effects[0].state == "implementing"


class TestWorkerResultOnBlockedIssue:
    """Test 3: WorkerResult on blocked issue -> ErrorEffect."""

    def test_blocked_issue_error(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create parent, advance to scoping
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["P"].state == "scoping"
        assert state.issues["P"].worker_active is True

        # Decompose: creates children, parent becomes blocked
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        # Parent should be blocked (children not terminal)
        # Trying to send WorkerResult to blocked parent should error
        # First, the parent's worker_active is False after decompose result
        # We need to set it True to test the blocked validation
        state.issues["P"].worker_active = True

        state2, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "implement"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "blocked" in effects[0].message.lower()


class TestWorkerResultOnTerminalIssue:
    """Test 4: WorkerResult on terminal issue -> ErrorEffect."""

    def test_terminal_issue_error(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "done"

        # Try sending result to terminal issue
        state2, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)


class TestWorkerResultWhenInactive:
    """Test 5: WorkerResult when worker_active=False -> ErrorEffect."""

    def test_worker_inactive_error(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        # Manually set worker_active to False
        state.issues["A"].worker_active = False

        state2, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "worker_active" in effects[0].message.lower() or "active" in effects[0].message.lower()


class TestUnknownOutcome:
    """Test 6: Unknown outcome -> ErrorEffect, state unchanged."""

    def test_unknown_outcome_error(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].worker_active is True
        assert state.issues["A"].state == "todo"

        state2, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "nonexistent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        # worker_active stays True since validation is before mutation
        assert state2.issues["A"].worker_active is True
        assert state2.issues["A"].state == "todo"


class TestDecomposeCreatesChildren:
    """Test 7: Decompose creates children with decomposed_from, parent stays in same state."""

    def test_children_created(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["P"].state == "scoping"

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "c1", "fields": {"title": "Child 1"}},
                        {"key": "c2", "fields": {"title": "Child 2"}},
                    ],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )

        # Parent stays in scoping state
        assert state.issues["P"].state == "scoping"
        assert state.issues["P"].worker_active is False

        # Children created
        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "P"]
        assert len(child_ids) == 2

        for cid in child_ids:
            child = state.issues[cid]
            assert child.decomposed_from == "P"
            assert child.state == config.initial  # "todo"


class TestDecomposeWithDependsOn:
    """Test 8: Decompose with key/depends_on, verify depends_on resolved to real IDs."""

    def test_depends_on_resolved(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "c1", "fields": {"title": "C1"}},
                        {"key": "c2", "fields": {"title": "C2"}, "depends_on": ["c1"]},
                    ],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )

        # Find the child that depends on the other
        children = {iid: iss for iid, iss in state.issues.items() if iss.decomposed_from == "P"}
        assert len(children) == 2

        # One child should have depends_on pointing to the real ID of c1
        dependent = [iss for iss in children.values() if iss.depends_on]
        assert len(dependent) == 1
        # The depends_on should contain the real ID of c1 (not the key "c1")
        dep_id = dependent[0].depends_on[0]
        assert dep_id in children  # the ID it depends on is a real child ID
        assert children[dep_id].depends_on == []  # c1 has no dependencies

        # The dependent child should NOT be dispatched (blocked)
        # The independent child should be dispatched
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        dispatched_ids = {e.issue_id for e in dispatch_effects}
        assert dep_id in dispatched_ids  # c1 is dispatched
        # The dependent child is blocked, not dispatched
        dependent_id = [iid for iid, iss in children.items() if iss.depends_on][0]
        assert dependent_id not in dispatched_ids


class TestEmptyDecompose:
    """Test 9: Empty decompose -> ErrorEffect."""

    def test_empty_sub_issues_error(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        state2, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={"outcome": "decompose", "sub_issues": []},
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )
        assert any(isinstance(e, ErrorEffect) for e in effects)
        # State should not be mutated (validation before mutation)
        assert state2.issues["P"].worker_active is True


class TestCascadingDecompositionUnblock:
    """Test 10: Child reaches terminal, parent unblocked and re-dispatched."""

    def test_parent_dispatched_when_all_children_done(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create parent, move to scoping
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Decompose into one child
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )

        # Find child ID
        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "P"]
        assert len(child_ids) == 1
        child_id = child_ids[0]

        # Child is in todo with worker active
        assert state.issues[child_id].state == "todo"
        assert state.issues[child_id].worker_active is True

        # Child: todo -> scoping via "scope"
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=child_id, result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues[child_id].state == "scoping"

        # Child: scoping -> implementing via "implement"
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=child_id, result={"outcome": "implement"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues[child_id].state == "implementing"

        # Child: implementing -> done via "complete"
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=child_id, result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues[child_id].state == "done"

        # Parent should be re-dispatched (unblocked)
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        parent_dispatched = [e for e in dispatch_effects if e.issue_id == "P"]
        assert len(parent_dispatched) == 1
        assert state.issues["P"].worker_active is True


class TestDependencyUnblock:
    """Test 11: Issue in depends_on reaches terminal, dependent issue gets dispatched."""

    def test_dependent_dispatched_when_dependency_done(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create parent, move to scoping, decompose with dependency
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "c1", "fields": {"title": "C1"}},
                        {"key": "c2", "fields": {"title": "C2"}, "depends_on": ["c1"]},
                    ],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )

        # Find children
        children = {iid: iss for iid, iss in state.issues.items() if iss.decomposed_from == "P"}
        c1_id = [iid for iid, iss in children.items() if not iss.depends_on][0]
        c2_id = [iid for iid, iss in children.items() if iss.depends_on][0]

        # c2 should not be dispatched (blocked by c1)
        assert state.issues[c2_id].worker_active is False

        # Complete c1: todo -> scoping -> implementing -> done
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=c1_id, result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=c1_id, result={"outcome": "implement"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=c1_id, result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues[c1_id].state == "done"

        # c2 should now be dispatched
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        c2_dispatched = [e for e in dispatch_effects if e.issue_id == c2_id]
        assert len(c2_dispatched) == 1
        assert state.issues[c2_id].worker_active is True


class TestSlotBackfillOnWorkerResult:
    """Test 12: Issue completes in max_workers state, next in queue dispatched."""

    def test_backfill_after_result(self, max_workers_config_yaml: str) -> None:
        config = parse_config(max_workers_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create two issues, both reach "apply" state (max_workers=1)
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "A"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "ready"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        # A is now in apply, dispatched
        assert state.issues["A"].state == "apply"
        assert state.issues["A"].worker_active is True

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="B", fields={"title": "B"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="B", result={"outcome": "start"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="B", result={"outcome": "ready"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        # B is in apply but queued (max_workers=1, A is active)
        assert state.issues["B"].state == "apply"
        assert state.issues["B"].worker_active is False

        # A completes apply -> done, B should be backfilled
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "applied"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "done"

        # B should now be dispatched
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        b_dispatched = [e for e in dispatch_effects if e.issue_id == "B"]
        assert len(b_dispatched) == 1
        assert state.issues["B"].worker_active is True


class TestDiamondDependency:
    """Test 13: Two issues depend on same issue, both unblock when it completes."""

    def test_diamond_unblock(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create parent, decompose into 3 children: c1, c2 depends on c1, c3 depends on c1
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "c1", "fields": {"title": "C1"}},
                        {"key": "c2", "fields": {"title": "C2"}, "depends_on": ["c1"]},
                        {"key": "c3", "fields": {"title": "C3"}, "depends_on": ["c1"]},
                    ],
                },
                timestamp="2026-01-01T00:00:00Z",
            ),
            gen,
            _clock(),
        )

        # Find children
        children = {iid: iss for iid, iss in state.issues.items() if iss.decomposed_from == "P"}
        c1_id = [iid for iid, iss in children.items() if not iss.depends_on][0]
        dependent_ids = [iid for iid, iss in children.items() if iss.depends_on]
        assert len(dependent_ids) == 2

        # Both dependents should be blocked
        for did in dependent_ids:
            assert state.issues[did].worker_active is False

        # Complete c1
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=c1_id, result={"outcome": "scope"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=c1_id, result={"outcome": "implement"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=c1_id, result={"outcome": "complete"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock(),
        )

        # Both c2 and c3 should now be dispatched
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        dispatched_ids = {e.issue_id for e in dispatch_effects}
        for did in dependent_ids:
            assert did in dispatched_ids
            assert state.issues[did].worker_active is True
