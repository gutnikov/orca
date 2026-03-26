from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    EnumFieldDef,
    FieldDef,
    State,
    StateDef,
    StateMachineConfig,
    TypeDef,
    WorkerDef,
    WorkerFailedEvent,
    WorkerResultEvent,
)


def _counter() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def _clock(value: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: value


def _passive_initial_config() -> StateMachineConfig:
    """Config where initial state 'backlog' is passive (no worker)."""
    return StateMachineConfig(
        root_type="default",
        types={
            "default": TypeDef(
                fields={"title": FieldDef(type="string", description="Title")},
                initial="backlog",
                states={
                    "backlog": StateDef(),
                    "todo": StateDef(
                        worker=WorkerDef(
                            kind="claude-code",
                            prompt="prompts/default.md",
                            result_format={
                                "outcome": EnumFieldDef(values=["start"], description="Decision"),
                            },
                        ),
                        on={},
                    ),
                    "done": StateDef(terminal=True),
                },
            )
        },
    )


def _active_initial_config() -> StateMachineConfig:
    """Config where initial state 'todo' is active (has worker)."""
    return StateMachineConfig(
        root_type="default",
        types={
            "default": TypeDef(
                fields={"title": FieldDef(type="string", description="Title")},
                initial="todo",
                states={
                    "todo": StateDef(
                        worker=WorkerDef(
                            kind="claude-code",
                            prompt="prompts/default.md",
                            result_format={
                                "outcome": EnumFieldDef(values=["done"], description="Decision"),
                            },
                        ),
                        on={
                            "done": __import__("orca.engine.types", fromlist=["OnTransition"]).OnTransition(
                                target="done"
                            )
                        },
                    ),
                    "done": StateDef(terminal=True),
                },
            )
        },
    )


class TestCreateLogsCreatedEntry:
    def test_create_logs_created_entry(self) -> None:
        config = _passive_initial_config()
        state = State(issues={}, worker_queues={})
        event = CreateEvent(issue_id="A", fields={"title": "My Issue"}, timestamp="2026-01-01T12:00:00Z")

        new_state, _effects = reduce(config, state, event, _counter(), _clock())

        issue = new_state.issues["A"]
        assert len(issue.event_log) == 1
        assert issue.event_log[0].type == "created"
        assert issue.event_log[0].timestamp == "2026-01-01T12:00:00Z"  # event.timestamp
        assert issue.event_log[0].data == {"state": "backlog"}


class TestCreateActiveLogsCreatedAndDispatched:
    def test_create_active_logs_created_and_dispatched(self) -> None:
        config = _active_initial_config()
        state = State(issues={}, worker_queues={})
        event = CreateEvent(issue_id="A", fields={"title": "My Issue"}, timestamp="2026-01-01T12:00:00Z")

        new_state, effects = reduce(config, state, event, _counter(), _clock("2026-01-01T12:00:01Z"))

        issue = new_state.issues["A"]
        assert len(issue.event_log) == 2
        assert issue.event_log[0].type == "created"
        assert issue.event_log[0].timestamp == "2026-01-01T12:00:00Z"
        assert issue.event_log[1].type == "worker_dispatched"
        assert issue.event_log[1].timestamp == "2026-01-01T12:00:01Z"
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)


class TestAdvanceLogsAdvancedEntry:
    def test_advance_logs_advanced_entry(self) -> None:
        config = _passive_initial_config()
        state = State(issues={}, worker_queues={})
        gen = _counter()
        clock = _clock("2026-01-01T12:00:00Z")

        # Create issue first
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T11:00:00Z"),
            gen,
            clock,
        )

        # Advance to todo (active)
        state, _effects = reduce(
            config,
            state,
            AdvanceEvent(issue_id="A", target_state="todo", timestamp="2026-01-01T12:00:00Z"),
            gen,
            _clock("2026-01-01T12:00:01Z"),
        )

        issue = state.issues["A"]
        # Should have: created, advanced, worker_dispatched
        advanced_entries = [e for e in issue.event_log if e.type == "advanced"]
        assert len(advanced_entries) == 1
        assert advanced_entries[0].timestamp == "2026-01-01T12:00:00Z"
        assert advanced_entries[0].data == {"from": "backlog", "to": "todo"}


class TestAdvanceDoesNotLogTransitioned:
    def test_advance_does_not_log_transitioned(self) -> None:
        config = _passive_initial_config()
        state = State(issues={}, worker_queues={})
        gen = _counter()
        clock = _clock()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            clock,
        )

        state, _ = reduce(
            config,
            state,
            AdvanceEvent(issue_id="A", target_state="todo", timestamp="2026-01-01T00:00:01Z"),
            gen,
            clock,
        )

        issue = state.issues["A"]
        transitioned_entries = [e for e in issue.event_log if e.type == "transitioned"]
        assert len(transitioned_entries) == 0


class TestWorkerResultLogsResultAndTransition:
    def test_worker_result_logs_result_and_transition(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create issue in todo (active)
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock("2026-01-01T00:00:00Z"),
        )

        # Worker result: start -> implementing
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:01:00Z"),
            gen,
            _clock("2026-01-01T00:01:01Z"),
        )

        issue = state.issues["A"]
        result_entries = [e for e in issue.event_log if e.type == "worker_result"]
        assert len(result_entries) == 1
        assert result_entries[0].timestamp == "2026-01-01T00:01:00Z"
        assert result_entries[0].data == {"outcome": "start"}

        transitioned_entries = [e for e in issue.event_log if e.type == "transitioned"]
        assert len(transitioned_entries) == 1
        assert transitioned_entries[0].timestamp == "2026-01-01T00:01:01Z"
        assert transitioned_entries[0].data == {"from": "todo", "to": "implementing"}


class TestWorkerFailedLogsFailedAndDispatch:
    def test_worker_failed_logs_failed_and_dispatch(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock("2026-01-01T00:00:00Z"),
        )

        state, effects = reduce(
            config,
            state,
            WorkerFailedEvent(issue_id="A", error="timeout", timestamp="2026-01-01T00:01:00Z"),
            gen,
            _clock("2026-01-01T00:01:01Z"),
        )

        issue = state.issues["A"]
        failed_entries = [e for e in issue.event_log if e.type == "worker_failed"]
        assert len(failed_entries) == 1
        assert failed_entries[0].timestamp == "2026-01-01T00:01:00Z"
        assert failed_entries[0].data == {"state": "todo", "error": "timeout"}

        dispatched_entries = [e for e in issue.event_log if e.type == "worker_dispatched"]
        # One from create + one from retry
        assert len(dispatched_entries) == 2
        assert dispatched_entries[1].timestamp == "2026-01-01T00:01:01Z"


class TestDecomposeLogsBlockedAndChildCreated:
    def test_decompose_logs_blocked_and_child_created(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="P", fields={"title": "Parent"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock("2026-01-01T00:00:00Z"),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp="2026-01-01T00:01:00Z"),
            gen,
            _clock("2026-01-01T00:01:00Z"),
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
                        {"key": "c2", "fields": {"title": "C2"}},
                    ],
                },
                timestamp="2026-01-01T00:02:00Z",
            ),
            gen,
            _clock("2026-01-01T00:02:01Z"),
        )

        parent = state.issues["P"]
        blocked_entries = [e for e in parent.event_log if e.type == "decomposition_blocked"]
        assert len(blocked_entries) == 1

        # Children should have "created" entries
        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "P"]
        assert len(child_ids) == 2
        for cid in child_ids:
            child = state.issues[cid]
            created_entries = [e for e in child.event_log if e.type == "created"]
            assert len(created_entries) == 1


class TestUnblockLogsUnblockedEntry:
    def test_unblock_logs_unblocked_entry(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()
        ts = "2026-01-01T00:00:00Z"

        # Create parent, scope, decompose into 1 child
        state, _ = reduce(
            config, state, CreateEvent(issue_id="P", fields={"title": "P"}, timestamp=ts), gen, _clock(ts)
        )
        state, _ = reduce(
            config, state, WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp=ts), gen, _clock(ts)
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="P",
                result={"outcome": "decompose", "sub_issues": [{"key": "c1", "fields": {"title": "C1"}}]},
                timestamp=ts,
            ),
            gen,
            _clock(ts),
        )

        child_id = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "P"][0]

        # Complete child: todo -> scoping -> implementing -> done
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=child_id, result={"outcome": "scope"}, timestamp=ts),
            gen,
            _clock(ts),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=child_id, result={"outcome": "implement"}, timestamp=ts),
            gen,
            _clock(ts),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=child_id, result={"outcome": "complete"}, timestamp=ts),
            gen,
            _clock(ts),
        )

        assert state.issues[child_id].state == "done"

        # Parent should have unblocked entry
        parent = state.issues["P"]
        unblocked_entries = [e for e in parent.event_log if e.type == "unblocked"]
        assert len(unblocked_entries) == 1
        assert unblocked_entries[0].data == {"reason": "decomposition"}


class TestDependencyUnblockLogsEntry:
    def test_dependency_unblock_logs_entry(self, decompose_config_yaml: str) -> None:
        config = parse_config(decompose_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()
        ts = "2026-01-01T00:00:00Z"

        # Create parent, scope, decompose with dependency
        state, _ = reduce(
            config, state, CreateEvent(issue_id="P", fields={"title": "P"}, timestamp=ts), gen, _clock(ts)
        )
        state, _ = reduce(
            config, state, WorkerResultEvent(issue_id="P", result={"outcome": "scope"}, timestamp=ts), gen, _clock(ts)
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
                timestamp=ts,
            ),
            gen,
            _clock(ts),
        )

        children = {iid: iss for iid, iss in state.issues.items() if iss.decomposed_from == "P"}
        c1_id = [iid for iid, iss in children.items() if not iss.depends_on][0]
        c2_id = [iid for iid, iss in children.items() if iss.depends_on][0]

        # Complete c1
        state, _ = reduce(
            config, state, WorkerResultEvent(issue_id=c1_id, result={"outcome": "scope"}, timestamp=ts), gen, _clock(ts)
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=c1_id, result={"outcome": "implement"}, timestamp=ts),
            gen,
            _clock(ts),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id=c1_id, result={"outcome": "complete"}, timestamp=ts),
            gen,
            _clock(ts),
        )

        assert state.issues[c1_id].state == "done"

        # c2 should have unblocked entry with reason="dependency"
        c2 = state.issues[c2_id]
        unblocked_entries = [e for e in c2.event_log if e.type == "unblocked"]
        assert len(unblocked_entries) == 1
        assert unblocked_entries[0].data == {"reason": "dependency"}


class TestEventLogTimestampsUseEventTimestamp:
    def test_event_log_timestamps_use_event_timestamp(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
            gen,
            _clock("2026-01-01T00:00:01Z"),
        )

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="2026-01-01T00:01:00Z"),
            gen,
            _clock("2026-01-01T00:01:05Z"),
        )

        issue = state.issues["A"]
        # worker_result uses event.timestamp
        result_entry = [e for e in issue.event_log if e.type == "worker_result"][0]
        assert result_entry.timestamp == "2026-01-01T00:01:00Z"

        # transitioned uses now()
        transitioned_entry = [e for e in issue.event_log if e.type == "transitioned"][0]
        assert transitioned_entry.timestamp == "2026-01-01T00:01:05Z"


class TestFullLifecycleLog:
    def test_full_lifecycle_log(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="T0"),
            gen,
            _clock("NOW0"),
        )

        # Worker result: start -> implementing
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "start"}, timestamp="T1"),
            gen,
            _clock("NOW1"),
        )

        # Worker result: complete -> done
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "complete"}, timestamp="T2"),
            gen,
            _clock("NOW2"),
        )

        issue = state.issues["A"]
        types = [e.type for e in issue.event_log]
        assert types == [
            "created",  # from create
            "worker_dispatched",  # from create (active initial)
            "worker_result",  # from first WorkerResult
            "transitioned",  # todo -> implementing
            "worker_dispatched",  # implementing dispatched
            "worker_result",  # from second WorkerResult
            "transitioned",  # implementing -> done
        ]

        assert issue.state == "done"
        assert issue.worker_active is False
