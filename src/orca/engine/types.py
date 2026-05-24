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
    inactivity_timeout: int | None = None
    model: str | None = None
    args: tuple[str, ...] | None = None
    progress: bool = False
    # When True, `prompt` holds inline Jinja template source.
    # When False (default), `prompt` is a path (relative to flow_root) to a template file.
    prompt_inline: bool = False


@dataclass(frozen=True)
class OnTransition:
    target: str


@dataclass(frozen=True)
class OnDecompose:
    child_type: str | None = None
    then: str | None = None


OnRule = OnTransition | OnDecompose

BUILTIN_STATES: frozenset[str] = frozenset({"done", "failed"})


@dataclass(frozen=True)
class StateDef:
    worker: WorkerDef | None = None
    on: dict[str, OnRule] = field(default_factory=dict)
    max_workers: int | None = None


@dataclass(frozen=True)
class TypeDef:
    fields: dict[str, FieldDef]
    initial: str
    states: dict[str, StateDef]


_DONE_SENTINEL = StateDef()


@dataclass(frozen=True)
class StateMachineConfig:
    root_type: str
    types: dict[str, TypeDef]
    max_hops: int | None = None
    max_worker_retries: int | None = None

    def get_type(self, type_name: str) -> TypeDef:
        return self.types[type_name]

    def get_state(self, type_name: str, state_name: str) -> StateDef:
        if state_name == "done":
            return _DONE_SENTINEL
        return self.types[type_name].states[state_name]

    @property
    def root_type_def(self) -> TypeDef:
        return self.types[self.root_type]


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
    type: str
    fields: dict[str, Any]
    state: str
    worker_active: bool
    decomposed_from: str | None
    depends_on: list[str]
    event_log: list[EventLogEntry]
    visit_counts: dict[str, int] = field(default_factory=dict)
    hop_count: int = 0
    failure_count: int = 0
    state_base_commit: str | None = None
    debug_pending: bool = False
    modify_pending: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "fields": self.fields,
            "state": self.state,
            "worker_active": self.worker_active,
            "decomposed_from": self.decomposed_from,
            "depends_on": self.depends_on,
            "event_log": [entry.to_dict() for entry in self.event_log],
            "visit_counts": self.visit_counts,
            "hop_count": self.hop_count,
            "failure_count": self.failure_count,
            "state_base_commit": self.state_base_commit,
            "debug_pending": self.debug_pending,
            "modify_pending": self.modify_pending,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Issue:
        return cls(
            type=data["type"],
            fields=data["fields"],
            state=data["state"],
            worker_active=data["worker_active"],
            decomposed_from=data["decomposed_from"],
            depends_on=data["depends_on"],
            event_log=[EventLogEntry.from_dict(e) for e in data.get("event_log", [])],
            visit_counts=data.get("visit_counts", {}),
            hop_count=data.get("hop_count", 0),
            failure_count=data.get("failure_count", 0),
            state_base_commit=data.get("state_base_commit"),
            debug_pending=data.get("debug_pending", False),
            modify_pending=data.get("modify_pending", False),
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


@dataclass(frozen=True)
class WorkerWaitingEvent:
    issue_id: str
    reason: str
    timestamp: str


@dataclass(frozen=True)
class WorkerResumedEvent:
    issue_id: str
    message: str
    timestamp: str


@dataclass(frozen=True)
class DebugReviewRequiredEvent:
    issue_id: str
    snapshot: DebugReviewSnapshot
    timestamp: str


@dataclass(frozen=True)
class DebugDecisionEvent:
    issue_id: str
    action: str  # "accept" | "restart" | "modify_restart" | "stop"
    comments: list[InlineComment]
    timestamp: str


@dataclass(frozen=True)
class DebugModifyRequestEvent:
    issue_id: str
    comments: list[InlineComment]
    timestamp: str


Event = (
    CreateEvent
    | AdvanceEvent
    | WorkerResultEvent
    | WorkerFailedEvent
    | WorkerWaitingEvent
    | WorkerResumedEvent
    | DebugReviewRequiredEvent
    | DebugDecisionEvent
    | DebugModifyRequestEvent
)


# --- Effects (frozen) ---


@dataclass(frozen=True)
class DispatchWorkerEffect:
    issue_id: str
    issue_type: str
    state: str
    result_format: dict[str, Any]
    issue: dict[str, Any]
    progress_enabled: bool = False


@dataclass(frozen=True)
class ErrorEffect:
    issue_id: str
    message: str


Effect = DispatchWorkerEffect | ErrorEffect


# --- Debug review (mutable, with serialization) ---


@dataclass
class InlineComment:
    file: str
    line: int | None
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "body": self.body}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InlineComment:
        return cls(file=data["file"], line=data.get("line"), body=data["body"])


@dataclass
class Hunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_start": self.old_start,
            "old_lines": self.old_lines,
            "new_start": self.new_start,
            "new_lines": self.new_lines,
            "lines": self.lines,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hunk:
        return cls(
            old_start=data["old_start"],
            old_lines=data["old_lines"],
            new_start=data["new_start"],
            new_lines=data["new_lines"],
            lines=data["lines"],
        )


@dataclass
class DiffFile:
    path: str
    status: str  # "added" | "modified" | "deleted" | "renamed"
    hunks: list[Hunk]
    # Raw unified-diff text for this file (the `diff --git ...` block including
    # `+++/---` headers and `@@` hunks). The web review UI's DiffView re-parses
    # this string to render the side-by-side / inline view; pre-parsed `hunks`
    # are kept for any consumer that wants a typed structure without re-parsing.
    raw_diff: str = ""
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "hunks": [h.to_dict() for h in self.hunks],
            "diff": self.raw_diff,
            "additions": self.additions,
            "deletions": self.deletions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffFile:
        return cls(
            path=data["path"],
            status=data["status"],
            hunks=[Hunk.from_dict(h) for h in data["hunks"]],
            raw_diff=data.get("diff", ""),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
        )


@dataclass
class DebugReviewSnapshot:
    rendered_prompt: str
    worker_result: dict[str, Any]
    config_slice: str
    diff_files: list[DiffFile]
    base_commit: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rendered_prompt": self.rendered_prompt,
            "worker_result": self.worker_result,
            "config_slice": self.config_slice,
            "diff_files": [f.to_dict() for f in self.diff_files],
            "base_commit": self.base_commit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebugReviewSnapshot:
        return cls(
            rendered_prompt=data["rendered_prompt"],
            worker_result=data["worker_result"],
            config_slice=data["config_slice"],
            diff_files=[DiffFile.from_dict(f) for f in data["diff_files"]],
            base_commit=data["base_commit"],
        )
