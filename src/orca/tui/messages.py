from __future__ import annotations

from textual.message import Message

from orca.engine.types import State


class StateUpdated(Message):
    """Posted when state.json has changed on disk."""

    def __init__(self, state: State) -> None:
        super().__init__()
        self.state = state


class IssueSelected(Message):
    """Posted when the user selects an issue in the tree."""

    def __init__(self, issue_id: str) -> None:
        super().__init__()
        self.issue_id = issue_id
