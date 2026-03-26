from __future__ import annotations

from textual.message import Message

from orca.engine.types import State


class StateUpdated(Message):
    """Posted when state.json has changed on disk."""

    def __init__(self, state: State, sessions: list[dict[str, object]]) -> None:
        super().__init__()
        self.state = state
        self.sessions = sessions


class IssueSelected(Message):
    """Posted when the user highlights an issue node in the tree."""

    def __init__(self, issue_id: str) -> None:
        super().__init__()
        self.issue_id = issue_id


class WorkerRunSelected(Message):
    """Posted when the user highlights a worker-run leaf in the tree."""

    def __init__(
        self,
        session_id: str,
        active: bool = False,
        worktree_path: str = "",
        issue_id: str = "",
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self.active = active
        self.worktree_path = worktree_path
        self.issue_id = issue_id


class RetryIssue(Message):
    """Posted when the user requests a retry of a failed issue."""

    def __init__(self, issue_id: str) -> None:
        super().__init__()
        self.issue_id = issue_id


class InsightsSelected(Message):
    """Posted when the user highlights the Insights root node."""

    def __init__(self) -> None:
        super().__init__()


class InsightEntrySelected(Message):
    """Posted when the user highlights a specific insight entry."""

    def __init__(self, title: str, detail: str, remediation: str, severity: str) -> None:
        super().__init__()
        self.title = title
        self.detail = detail
        self.remediation = remediation
        self.severity = severity
