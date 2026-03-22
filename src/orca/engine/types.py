from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- Config types (frozen) ---


@dataclass(frozen=True)
class FieldDef:
    type: str
    description: str


@dataclass(frozen=True)
class EnumFieldDef:
    values: list[str]
    description: str
    values_description: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StringFieldDef:
    description: str
    required_when: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ListFieldDef:
    description: str
    items: str
    required_when: list[str] = field(default_factory=list)


ResultFormatField = EnumFieldDef | StringFieldDef | ListFieldDef


@dataclass(frozen=True)
class WorkerDef:
    result_format: dict[str, ResultFormatField]


@dataclass(frozen=True)
class OnTransition:
    target: str


@dataclass(frozen=True)
class OnDecompose:
    pass


OnRule = OnTransition | OnDecompose


@dataclass(frozen=True)
class StateDef:
    worker: WorkerDef | None = None
    on: dict[str, OnRule] = field(default_factory=dict)
    terminal: bool = False
    max_workers: int | None = None


@dataclass(frozen=True)
class StateMachineConfig:
    issue_fields: dict[str, FieldDef]
    initial: str
    states: dict[str, StateDef]


# --- Runtime state types (mutable, with serialization) ---


@dataclass
class ResultHistoryEntry:
    state: str
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "result": self.result}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResultHistoryEntry:
        return cls(state=data["state"], result=data["result"])


@dataclass
class Issue:
    fields: dict[str, Any]
    state: str
    worker_active: bool
    decomposed_from: str | None
    depends_on: list[str]
    result_history: list[ResultHistoryEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "state": self.state,
            "worker_active": self.worker_active,
            "decomposed_from": self.decomposed_from,
            "depends_on": self.depends_on,
            "result_history": [entry.to_dict() for entry in self.result_history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Issue:
        return cls(
            fields=data["fields"],
            state=data["state"],
            worker_active=data["worker_active"],
            decomposed_from=data["decomposed_from"],
            depends_on=data["depends_on"],
            result_history=[ResultHistoryEntry.from_dict(e) for e in data["result_history"]],
        )


@dataclass
class State:
    issues: dict[str, Issue]
    worker_queues: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": {k: v.to_dict() for k, v in self.issues.items()},
            "worker_queues": self.worker_queues,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        return cls(
            issues={k: Issue.from_dict(v) for k, v in data["issues"].items()},
            worker_queues=data["worker_queues"],
        )


# --- Events (frozen) ---


@dataclass(frozen=True)
class CreateEvent:
    issue_id: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class AdvanceEvent:
    issue_id: str
    target_state: str


@dataclass(frozen=True)
class WorkerResultEvent:
    issue_id: str
    result: dict[str, Any]


@dataclass(frozen=True)
class WorkerFailedEvent:
    issue_id: str
    error: str


Event = CreateEvent | AdvanceEvent | WorkerResultEvent | WorkerFailedEvent


# --- Effects (frozen) ---


@dataclass(frozen=True)
class DispatchWorkerEffect:
    issue_id: str
    state: str
    result_format: dict[str, Any]
    issue: dict[str, Any]


@dataclass(frozen=True)
class ErrorEffect:
    issue_id: str
    message: str


Effect = DispatchWorkerEffect | ErrorEffect
