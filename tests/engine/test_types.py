from __future__ import annotations

import json

from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    EnumFieldDef,
    ErrorEffect,
    FieldDef,
    Issue,
    ListFieldDef,
    OnDecompose,
    OnTransition,
    ResultHistoryEntry,
    State,
    StateDef,
    StateMachineConfig,
    StringFieldDef,
    WorkerDef,
    WorkerFailedEvent,
    WorkerResultEvent,
)


class TestIssueConstruction:
    def test_issue_with_all_dag_fields(self) -> None:
        issue = Issue(
            fields={"title": "Fix bug", "priority": "high"},
            state="open",
            worker_active=False,
            decomposed_from="PARENT-1",
            depends_on=["DEP-1", "DEP-2"],
            result_history=[],
        )
        assert issue.fields == {"title": "Fix bug", "priority": "high"}
        assert issue.state == "open"
        assert issue.worker_active is False
        assert issue.decomposed_from == "PARENT-1"
        assert issue.depends_on == ["DEP-1", "DEP-2"]
        assert issue.result_history == []

    def test_issue_without_decomposed_from(self) -> None:
        issue = Issue(
            fields={"title": "Root issue"},
            state="open",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            result_history=[],
        )
        assert issue.decomposed_from is None


class TestSerializationRoundTrip:
    def test_state_round_trip(self) -> None:
        state = State(
            issues={
                "ISS-1": Issue(
                    fields={"title": "Do thing"},
                    state="open",
                    worker_active=False,
                    decomposed_from=None,
                    depends_on=[],
                    result_history=[],
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

    def test_state_with_result_history_round_trip(self) -> None:
        state = State(
            issues={
                "ISS-1": Issue(
                    fields={"title": "Task"},
                    state="review",
                    worker_active=False,
                    decomposed_from=None,
                    depends_on=[],
                    result_history=[
                        ResultHistoryEntry(state="triage", result={"decision": "approve"}),
                        ResultHistoryEntry(state="review", result={"verdict": "pass"}),
                    ],
                ),
            },
            worker_queues={},
        )
        d = state.to_dict()
        json_str = json.dumps(d)
        restored = State.from_dict(json.loads(json_str))
        assert len(restored.issues["ISS-1"].result_history) == 2
        assert restored.issues["ISS-1"].result_history[0].state == "triage"
        assert restored.issues["ISS-1"].result_history[0].result == {"decision": "approve"}
        assert restored.issues["ISS-1"].result_history[1].state == "review"
        assert restored.issues["ISS-1"].result_history[1].result == {"verdict": "pass"}

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
                    fields={},
                    state="blocked",
                    worker_active=False,
                    decomposed_from="ISS-0",
                    depends_on=["ISS-2", "ISS-3"],
                    result_history=[],
                ),
            },
            worker_queues={},
        )
        d = state.to_dict()
        json_str = json.dumps(d)
        restored = State.from_dict(json.loads(json_str))
        assert restored.issues["ISS-1"].decomposed_from == "ISS-0"
        assert restored.issues["ISS-1"].depends_on == ["ISS-2", "ISS-3"]


class TestEvents:
    def test_create_event(self) -> None:
        e = CreateEvent(issue_id="ISS-1", fields={"title": "New"})
        assert e.issue_id == "ISS-1"
        assert e.fields == {"title": "New"}

    def test_advance_event(self) -> None:
        e = AdvanceEvent(issue_id="ISS-1", target_state="review")
        assert e.issue_id == "ISS-1"
        assert e.target_state == "review"

    def test_worker_result_event(self) -> None:
        e = WorkerResultEvent(issue_id="ISS-1", result={"decision": "approve"})
        assert e.issue_id == "ISS-1"
        assert e.result == {"decision": "approve"}

    def test_worker_failed_event(self) -> None:
        e = WorkerFailedEvent(issue_id="ISS-1", error="timeout")
        assert e.issue_id == "ISS-1"
        assert e.error == "timeout"


class TestEffects:
    def test_dispatch_worker_effect(self) -> None:
        e = DispatchWorkerEffect(
            issue_id="ISS-1",
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
            result_format={
                "decision": EnumFieldDef(values=["approve", "reject"], description="Decision"),
            }
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
        assert s.terminal is False
        assert s.max_workers is None

    def test_state_def_active(self) -> None:
        worker = WorkerDef(
            result_format={
                "decision": EnumFieldDef(values=["approve"], description="Decision"),
            }
        )
        s = StateDef(
            worker=worker,
            on={"approve": OnTransition(target="done")},
            max_workers=3,
        )
        assert s.worker is worker
        assert s.on == {"approve": OnTransition(target="done")}
        assert s.max_workers == 3

    def test_state_def_terminal(self) -> None:
        s = StateDef(terminal=True)
        assert s.terminal is True

    def test_state_machine_config(self) -> None:
        config = StateMachineConfig(
            issue_fields={
                "title": FieldDef(type="string", description="Title"),
                "priority": FieldDef(type="enum", description="Priority level"),
            },
            initial="triage",
            states={
                "triage": StateDef(
                    worker=WorkerDef(
                        result_format={
                            "decision": EnumFieldDef(values=["accept", "reject"], description="Decision"),
                        }
                    ),
                    on={
                        "accept": OnTransition(target="in_progress"),
                        "reject": OnTransition(target="closed"),
                    },
                ),
                "in_progress": StateDef(),
                "closed": StateDef(terminal=True),
            },
        )
        assert config.initial == "triage"
        assert len(config.states) == 3
        assert config.states["closed"].terminal is True
        assert len(config.issue_fields) == 2
