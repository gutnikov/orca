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
    kind: str
    prompt: str
    result_format: dict[str, ResultFormatField]
    timeout: int | None = None


@dataclass(frozen=True)
class OnTransition:
    target: str


@dataclass(frozen=True)
class OnDecompose:
    then: str | None = None


OnRule = OnTransition | OnDecompose


@dataclass(frozen=True)
class StateDef:
    worker: WorkerDef | None = None
    on: dict[str, OnRule] = field(default_factory=dict)
    terminal: bool = False
    max_workers: int | None = None
    max_visits: int | None = None


@dataclass(frozen=True)
class StateMachineConfig:
    issue_fields: dict[str, FieldDef]
    initial: str
    states: dict[str, StateDef]
    max_hops: int | None = None


# --- Runtime state types (mutable, with serialization) ---


@dataclass
class EventLogEntry:
    timestamp: str  # ISO 8601
    type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "type": self.type, "data": self.data}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventLogEntry:
        return cls(timestamp=data["timestamp"], type=data["type"], data=data["data"])


@dataclass
class Issue:
    fields: dict[str, Any]
    state: str
    worker_active: bool
    decomposed_from: str | None
    depends_on: list[str]
    event_log: list[EventLogEntry]
    visit_counts: dict[str, int] = field(default_factory=dict)
    hop_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "state": self.state,
            "worker_active": self.worker_active,
            "decomposed_from": self.decomposed_from,
            "depends_on": self.depends_on,
            "event_log": [entry.to_dict() for entry in self.event_log],
            "visit_counts": self.visit_counts,
            "hop_count": self.hop_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Issue:
        return cls(
            fields=data["fields"],
            state=data["state"],
            worker_active=data["worker_active"],
            decomposed_from=data["decomposed_from"],
            depends_on=data["depends_on"],
            event_log=[EventLogEntry.from_dict(e) for e in data.get("event_log", [])],
            visit_counts=data.get("visit_counts", {}),
            hop_count=data.get("hop_count", 0),
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
    timestamp: str


@dataclass(frozen=True)
class AdvanceEvent:
    issue_id: str
    target_state: str
    timestamp: str


@dataclass(frozen=True)
class WorkerResultEvent:
    issue_id: str
    result: dict[str, Any]
    timestamp: str


@dataclass(frozen=True)
class WorkerFailedEvent:
    issue_id: str
    error: str
    timestamp: str


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
