from __future__ import annotations

import json

import pytest

from orca.engine.types import (
    BUILTIN_STATES,
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    EnumFieldDef,
    ErrorEffect,
    Event,
    EventLogEntry,
    FieldDef,
    Issue,
    ListFieldDef,
    OnDecompose,
    OnTransition,
    State,
    StateDef,
    StateMachineConfig,
    StringFieldDef,
    TypeDef,
    WorkerDef,
    WorkerFailedEvent,
    WorkerResultEvent,
    WorkerResumedEvent,
    WorkerWaitingEvent,
)


def test_builtin_states_contains_done_and_failed() -> None:
    assert frozenset({"done", "failed"}) == BUILTIN_STATES


def test_state_def_has_no_terminal_field() -> None:
    sd = StateDef()
    assert not hasattr(sd, "terminal")


class TestIssueConstruction:
    def test_issue_with_all_dag_fields(self) -> None:
        issue = Issue(
            type="issue",
            fields={"title": "Fix bug", "priority": "high"},
            state="open",
            worker_active=False,
            decomposed_from="PARENT-1",
            depends_on=["DEP-1", "DEP-2"],
            event_log=[],
            visit_counts={},
            hop_count=0,
        )
        assert issue.fields == {"title": "Fix bug", "priority": "high"}
        assert issue.state == "open"
        assert issue.worker_active is False
        assert issue.decomposed_from == "PARENT-1"
        assert issue.depends_on == ["DEP-1", "DEP-2"]
        assert issue.event_log == []
        assert issue.visit_counts == {}
        assert issue.hop_count == 0

    def test_issue_without_decomposed_from(self) -> None:
        issue = Issue(
            type="issue",
            fields={"title": "Root issue"},
            state="open",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
            visit_counts={},
            hop_count=0,
        )
        assert issue.decomposed_from is None


class TestEventLogEntry:
    def test_construction(self) -> None:
        entry = EventLogEntry(
            timestamp="2026-03-22T10:00:00Z",
            type="worker_result",
            data={"outcome": "approve"},
        )
        assert entry.timestamp == "2026-03-22T10:00:00Z"
        assert entry.type == "worker_result"
        assert entry.data == {"outcome": "approve"}

    def test_round_trip(self) -> None:
        entry = EventLogEntry(
            timestamp="2026-03-22T10:00:00Z",
            type="advance",
            data={"target_state": "review"},
        )
        d = entry.to_dict()
        restored = EventLogEntry.from_dict(d)
        assert restored.timestamp == entry.timestamp
        assert restored.type == entry.type
        assert restored.data == entry.data


class TestSerializationRoundTrip:
    def test_state_round_trip(self) -> None:
        state = State(
            issues={
                "ISS-1": Issue(
                    type="issue",
                    fields={"title": "Do thing"},
                    state="open",
                    worker_active=False,
                    decomposed_from=None,
                    depends_on=[],
                    event_log=[],
                    visit_counts={},
                    hop_count=0,
                ),
            },
            worker_queues={},
        )
        d = state.to_dict()
        json_str = json.dumps(d)
        restored = State.from_dict(json.loads(json_str))
        assert restored.issues["ISS-1"].fields == {"title": "Do thing"}
        assert restored.issues["ISS-1"].state == "open"
        assert restored.issues["ISS-1"].worker_active is False
        assert restored.issues["ISS-1"].decomposed_from is None
        assert restored.issues["ISS-1"].depends_on == []

    def test_state_with_event_log_round_trip(self) -> None:
        state = State(
            issues={
                "ISS-1": Issue(
                    type="issue",
                    fields={"title": "Task"},
                    state="review",
                    worker_active=False,
                    decomposed_from=None,
                    depends_on=[],
                    event_log=[
                        EventLogEntry(
                            timestamp="2026-03-22T10:00:00Z",
                            type="worker_result",
                            data={"decision": "approve"},
                        ),
                        EventLogEntry(
                            timestamp="2026-03-22T11:00:00Z",
                            type="advance",
                            data={"target_state": "review"},
                        ),
                    ],
                    visit_counts={"triage": 1, "review": 1},
                    hop_count=2,
                ),
            },
            worker_queues={},
        )
        d = state.to_dict()
        json_str = json.dumps(d)
        restored = State.from_dict(json.loads(json_str))
        assert len(restored.issues["ISS-1"].event_log) == 2
        assert restored.issues["ISS-1"].event_log[0].type == "worker_result"
        assert restored.issues["ISS-1"].event_log[0].data == {"decision": "approve"}
        assert restored.issues["ISS-1"].event_log[1].type == "advance"
        assert restored.issues["ISS-1"].visit_counts == {"triage": 1, "review": 1}
        assert restored.issues["ISS-1"].hop_count == 2

    def test_state_with_worker_queues_round_trip(self) -> None:
        state = State(
            issues={},
            worker_queues={"triage": ["ISS-1", "ISS-2"], "review": ["ISS-3"]},
        )
        d = state.to_dict()
        json_str = json.dumps(d)
        restored = State.from_dict(json.loads(json_str))
        assert restored.worker_queues == {"triage": ["ISS-1", "ISS-2"], "review": ["ISS-3"]}

    def test_state_with_depends_on_round_trip(self) -> None:
        state = State(
            issues={
                "ISS-1": Issue(
                    type="issue",
                    fields={},
                    state="blocked",
                    worker_active=False,
                    decomposed_from="ISS-0",
                    depends_on=["ISS-2", "ISS-3"],
                    event_log=[],
                    visit_counts={},
                    hop_count=0,
                ),
            },
            worker_queues={},
        )
        d = state.to_dict()
        json_str = json.dumps(d)
        restored = State.from_dict(json.loads(json_str))
        assert restored.issues["ISS-1"].decomposed_from == "ISS-0"
        assert restored.issues["ISS-1"].depends_on == ["ISS-2", "ISS-3"]

    def test_issue_visit_counts_hop_count_round_trip(self) -> None:
        issue = Issue(
            type="issue",
            fields={"title": "Test"},
            state="review",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
            visit_counts={"triage": 2, "review": 1},
            hop_count=3,
        )
        d = issue.to_dict()
        restored = Issue.from_dict(d)
        assert restored.visit_counts == {"triage": 2, "review": 1}
        assert restored.hop_count == 3

    def test_issue_from_dict_backward_compat(self) -> None:
        """from_dict handles missing visit_counts, hop_count, and event_log."""
        raw = {
            "type": "issue",
            "fields": {"title": "Old"},
            "state": "open",
            "worker_active": False,
            "decomposed_from": None,
            "depends_on": [],
        }
        issue = Issue.from_dict(raw)
        assert issue.event_log == []
        assert issue.visit_counts == {}
        assert issue.hop_count == 0


class TestEvents:
    def test_create_event(self) -> None:
        e = CreateEvent(issue_id="ISS-1", fields={"title": "New"}, timestamp="2026-03-22T10:00:00Z")
        assert e.issue_id == "ISS-1"
        assert e.fields == {"title": "New"}
        assert e.timestamp == "2026-03-22T10:00:00Z"

    def test_advance_event(self) -> None:
        e = AdvanceEvent(issue_id="ISS-1", target_state="review", timestamp="2026-03-22T10:00:00Z")
        assert e.issue_id == "ISS-1"
        assert e.target_state == "review"
        assert e.timestamp == "2026-03-22T10:00:00Z"

    def test_worker_result_event(self) -> None:
        e = WorkerResultEvent(issue_id="ISS-1", result={"decision": "approve"}, timestamp="2026-03-22T10:00:00Z")
        assert e.issue_id == "ISS-1"
        assert e.result == {"decision": "approve"}
        assert e.timestamp == "2026-03-22T10:00:00Z"

    def test_worker_failed_event(self) -> None:
        e = WorkerFailedEvent(issue_id="ISS-1", error="timeout", timestamp="2026-03-22T10:00:00Z")
        assert e.issue_id == "ISS-1"
        assert e.error == "timeout"
        assert e.timestamp == "2026-03-22T10:00:00Z"


class TestEffects:
    def test_dispatch_worker_effect(self) -> None:
        e = DispatchWorkerEffect(
            issue_id="ISS-1",
            issue_type="issue",
            state="triage",
            result_format={"decision": {"type": "enum", "values": ["approve", "reject"]}},
            issue={"title": "Fix bug"},
        )
        assert e.issue_id == "ISS-1"
        assert e.state == "triage"
        assert e.result_format["decision"]["type"] == "enum"
        assert e.issue == {"title": "Fix bug"}

    def test_error_effect(self) -> None:
        e = ErrorEffect(issue_id="ISS-1", message="not found")
        assert e.issue_id == "ISS-1"
        assert e.message == "not found"


class TestConfigTypes:
    def test_field_def(self) -> None:
        f = FieldDef(type="string", description="The title")
        assert f.type == "string"
        assert f.description == "The title"

    def test_enum_field_def(self) -> None:
        f = EnumFieldDef(values=["low", "high"], description="Priority")
        assert f.values == ["low", "high"]
        assert f.description == "Priority"
        assert f.values_description == {}

    def test_enum_field_def_with_values_description(self) -> None:
        f = EnumFieldDef(
            values=["low", "high"],
            description="Priority",
            values_description={"low": "Not urgent", "high": "Urgent"},
        )
        assert f.values_description == {"low": "Not urgent", "high": "Urgent"}

    def test_string_field_def(self) -> None:
        f = StringFieldDef(description="A reason")
        assert f.description == "A reason"
        assert f.required_when == []

    def test_string_field_def_with_required_when(self) -> None:
        f = StringFieldDef(description="A reason", required_when=["rejected"])
        assert f.required_when == ["rejected"]

    def test_list_field_def(self) -> None:
        f = ListFieldDef(description="Sub-tasks", items="string")
        assert f.description == "Sub-tasks"
        assert f.items == "string"
        assert f.required_when == []

    def test_list_field_def_with_required_when(self) -> None:
        f = ListFieldDef(description="Sub-tasks", items="string", required_when=["decompose"])
        assert f.required_when == ["decompose"]

    def test_worker_def(self) -> None:
        w = WorkerDef(
            kind="claude-code",
            prompt="prompts/default.md",
            result_format={
                "decision": EnumFieldDef(values=["approve", "reject"], description="Decision"),
            },
        )
        assert "decision" in w.result_format

    def test_on_transition(self) -> None:
        t = OnTransition(target="review")
        assert t.target == "review"

    def test_on_decompose(self) -> None:
        d = OnDecompose()
        assert isinstance(d, OnDecompose)

    def test_state_def_passive(self) -> None:
        s = StateDef()
        assert s.worker is None
        assert s.on == {}
        assert s.max_workers is None

    def test_state_def_active(self) -> None:
        worker = WorkerDef(
            kind="claude-code",
            prompt="prompts/default.md",
            result_format={
                "decision": EnumFieldDef(values=["approve"], description="Decision"),
            },
        )
        s = StateDef(
            worker=worker,
            on={"approve": OnTransition(target="done")},
            max_workers=3,
        )
        assert s.worker is worker
        assert s.on == {"approve": OnTransition(target="done")}
        assert s.max_workers == 3

    def test_state_machine_config(self) -> None:
        td = TypeDef(
            fields={
                "title": FieldDef(type="string", description="Title"),
                "priority": FieldDef(type="enum", description="Priority level"),
            },
            initial="triage",
            states={
                "triage": StateDef(
                    worker=WorkerDef(
                        kind="claude-code",
                        prompt="prompts/default.md",
                        result_format={
                            "decision": EnumFieldDef(values=["accept", "reject"], description="Decision"),
                        },
                    ),
                    on={
                        "accept": OnTransition(target="in_progress"),
                        "reject": OnTransition(target="closed"),
                    },
                ),
                "in_progress": StateDef(),
                "closed": StateDef(),
            },
        )
        config = StateMachineConfig(root_type="issue", types={"issue": td})
        assert config.root_type_def.initial == "triage"
        assert len(config.root_type_def.states) == 3
        assert len(config.root_type_def.fields) == 2
        assert config.max_hops is None

    def test_state_machine_config_with_max_hops(self) -> None:
        td = TypeDef(
            fields={},
            initial="todo",
            states={"todo": StateDef()},
        )
        config = StateMachineConfig(
            root_type="issue",
            types={"issue": td},
            max_hops=50,
        )
        assert config.max_hops == 50


class TestTypeDef:
    def test_type_def_holds_fields_initial_states(self) -> None:
        td = TypeDef(
            fields={"title": FieldDef(type="string", description="t")},
            initial="todo",
            states={"todo": StateDef()},
        )
        assert td.initial == "todo"
        assert "title" in td.fields
        assert "todo" in td.states


class TestStateMachineConfigWithTypes:
    def test_config_has_root_type_and_types(self) -> None:
        td = TypeDef(
            fields={},
            initial="idle",
            states={"idle": StateDef()},
        )
        cfg = StateMachineConfig(
            root_type="epic",
            types={"epic": td},
            max_hops=None,
            max_worker_retries=None,
        )
        assert cfg.root_type == "epic"
        assert "epic" in cfg.types


class TestConfigHelpers:
    def _make_config(self) -> StateMachineConfig:
        worker = WorkerDef(
            kind="claude-code",
            prompt="p.md",
            result_format={"outcome": EnumFieldDef(values=["done"], description="d")},
        )
        epic = TypeDef(
            fields={"title": FieldDef(type="string", description="t")},
            initial="todo",
            states={
                "todo": StateDef(worker=worker, on={"done": OnTransition(target="done")}),
            },
        )
        return StateMachineConfig(root_type="epic", types={"epic": epic})

    def test_get_type_def(self) -> None:
        cfg = self._make_config()
        td = cfg.get_type("epic")
        assert td.initial == "todo"

    def test_get_state_def(self) -> None:
        cfg = self._make_config()
        sd = cfg.get_state("epic", "todo")
        assert sd.worker is not None

    def test_get_state_def_unknown_type_raises(self) -> None:
        cfg = self._make_config()
        with pytest.raises(KeyError):
            cfg.get_state("unknown", "todo")

    def test_root_type_def(self) -> None:
        cfg = self._make_config()
        td = cfg.root_type_def
        assert td.initial == "todo"


class TestOnDecomposeChildType:
    def test_child_type_default_none(self) -> None:
        rule = OnDecompose()
        assert rule.child_type is None
        assert rule.then is None

    def test_child_type_set(self) -> None:
        rule = OnDecompose(child_type="task", then="done")
        assert rule.child_type == "task"
        assert rule.then == "done"


class TestIssueType:
    def test_issue_has_type(self) -> None:
        issue = Issue(
            type="epic",
            fields={"title": "t"},
            state="todo",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
        )
        assert issue.type == "epic"

    def test_issue_to_dict_includes_type(self) -> None:
        issue = Issue(
            type="task",
            fields={},
            state="done",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
        )
        d = issue.to_dict()
        assert d["type"] == "task"

    def test_issue_from_dict_reads_type(self) -> None:
        d = {
            "type": "subtask",
            "fields": {},
            "state": "coding",
            "worker_active": False,
            "decomposed_from": None,
            "depends_on": [],
            "event_log": [],
        }
        issue = Issue.from_dict(d)
        assert issue.type == "subtask"


class TestDispatchWorkerEffectIssueType:
    def test_effect_has_issue_type(self) -> None:
        e = DispatchWorkerEffect(
            issue_id="I1",
            issue_type="task",
            state="implementing",
            result_format={},
            issue={},
        )
        assert e.issue_type == "task"


class TestBlockingEventTypes:
    def test_worker_waiting_event_fields(self) -> None:
        e = WorkerWaitingEvent(issue_id="ISS-1", timestamp="2026-04-04T10:00:00Z")
        assert e.issue_id == "ISS-1"
        assert e.timestamp == "2026-04-04T10:00:00Z"

    def test_worker_waiting_event_is_frozen(self) -> None:
        e = WorkerWaitingEvent(issue_id="ISS-1", timestamp="2026-04-04T10:00:00Z")
        with pytest.raises((AttributeError, TypeError)):
            e.issue_id = "OTHER"  # type: ignore[misc]

    def test_worker_resumed_event_fields(self) -> None:
        e = WorkerResumedEvent(issue_id="ISS-1", message="ready to proceed", timestamp="2026-04-04T11:00:00Z")
        assert e.issue_id == "ISS-1"
        assert e.message == "ready to proceed"
        assert e.timestamp == "2026-04-04T11:00:00Z"

    def test_worker_resumed_event_is_frozen(self) -> None:
        e = WorkerResumedEvent(issue_id="ISS-1", message="ok", timestamp="2026-04-04T11:00:00Z")
        with pytest.raises((AttributeError, TypeError)):
            e.issue_id = "OTHER"  # type: ignore[misc]

    def test_both_types_in_event_union(self) -> None:
        import typing

        args = typing.get_args(Event)
        assert WorkerWaitingEvent in args
        assert WorkerResumedEvent in args
