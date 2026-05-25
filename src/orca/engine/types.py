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
    # Reasoning-effort hint passed to the agent CLI when its kind supports
    # one (e.g. codex → `--reasoning-effort <effort>`). Silently dropped for
    # kinds that don't expose an effort flag. Typical values: low / medium /
    # high / xhigh.
    effort: str | None = None


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
    inline_comments: list[InlineComment] = field(default_factory=list)
    comment_threads: list[CommentThread] = field(default_factory=list)

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
            "inline_comments": [c.to_dict() for c in self.inline_comments],
            "comment_threads": [t.to_dict() for t in self.comment_threads],
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
            inline_comments=[InlineComment.from_dict(c) for c in data.get("inline_comments", [])],
            comment_threads=[CommentThread.from_dict(t) for t in data.get("comment_threads", [])],
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


@dataclass(frozen=True)
class InlineCommentSavedEvent:
    """User saved (created or edited) an inline review comment."""

    issue_id: str
    comment_id: str
    file: str
    line: int | None
    body: str
    timestamp: str


@dataclass(frozen=True)
class InlineCommentDeletedEvent:
    """User deleted an inline review comment (cascade-deletes its thread)."""

    issue_id: str
    comment_id: str
    timestamp: str


@dataclass(frozen=True)
class CommentThreadMessageAddedEvent:
    """A user-reply or agent-reply appended to a comment's thread.

    Lazily creates the CommentThread on the first message. Agent messages bump
    `agent_last_reviewed_at`; user messages don't.
    """

    issue_id: str
    comment_id: str
    role: str  # "user" | "agent"
    message_id: str
    body: str
    timestamp: str


@dataclass(frozen=True)
class CommentThreadReviewedEvent:
    """Agent reviewed the comment and chose not to engage. Bumps
    `agent_last_reviewed_at` without appending a message. Lazily creates an
    empty thread if none exists yet.
    """

    issue_id: str
    comment_id: str
    timestamp: str
    reason: str


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
    | InlineCommentSavedEvent
    | InlineCommentDeletedEvent
    | CommentThreadMessageAddedEvent
    | CommentThreadReviewedEvent
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
class ThreadMessage:
    id: str
    role: str  # "user" | "agent"
    body: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "role": self.role, "body": self.body, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThreadMessage:
        return cls(
            id=data["id"],
            role=data["role"],
            body=data["body"],
            timestamp=data["timestamp"],
        )


@dataclass
class CommentThread:
    id: str
    comment_id: str
    messages: list[ThreadMessage] = field(default_factory=list)
    agent_last_reviewed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "comment_id": self.comment_id,
            "messages": [m.to_dict() for m in self.messages],
            "agent_last_reviewed_at": self.agent_last_reviewed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommentThread:
        return cls(
            id=data["id"],
            comment_id=data["comment_id"],
            messages=[ThreadMessage.from_dict(m) for m in data.get("messages", [])],
            agent_last_reviewed_at=data.get("agent_last_reviewed_at"),
        )


@dataclass
class InlineComment:
    """A user-authored review comment, persisted on the issue during debug pause.

    Persisted on save (not just on decision submit) so the supervising agent
    can poll for new comments and engage with them in-place.
    """

    id: str
    file: str
    line: int | None
    body: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "line": self.line,
            "body": self.body,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InlineComment:
        # Back-compat: legacy decision-event payloads (pre-Task 3) only had {file, line, body}.
        # Backfill id/created_at/updated_at from data or sensible defaults.
        return cls(
            id=data.get("id", ""),
            file=data["file"],
            line=data.get("line"),
            body=data["body"],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


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
    # Optional full file contents at the base commit and at HEAD. Populated by
    # the orchestrator's snapshot builder so the web UI's "Full file" view mode
    # can render the entire file with added-line highlights — same UX as
    # GitHub's "Display the source diff" toggle. Empty string when the side
    # doesn't exist (e.g. old_content == "" for newly-added files).
    old_content: str = ""
    new_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "hunks": [h.to_dict() for h in self.hunks],
            "diff": self.raw_diff,
            "additions": self.additions,
            "deletions": self.deletions,
            "old_content": self.old_content,
            "new_content": self.new_content,
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
            old_content=data.get("old_content", ""),
            new_content=data.get("new_content", ""),
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
