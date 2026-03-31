from __future__ import annotations

from orca.engine.types import (
    DispatchFeedbackAgentEffect,
    Effect,
    Event,
    FeedbackReceivedEvent,
)


class TestFeedbackTypes:
    def test_dispatch_feedback_agent_effect_fields(self) -> None:
        effect = DispatchFeedbackAgentEffect(
            issue_id="issue-1",
            issue_type="default",
            state="implementing",
            questions="Which API should we target?",
            issue={"title": "Fix bug"},
        )
        assert effect.issue_id == "issue-1"
        assert effect.questions == "Which API should we target?"

    def test_dispatch_feedback_agent_effect_is_effect(self) -> None:
        effect = DispatchFeedbackAgentEffect(
            issue_id="issue-1",
            issue_type="default",
            state="implementing",
            questions="Q?",
            issue={},
        )
        assert isinstance(effect, DispatchFeedbackAgentEffect)
        effects: list[Effect] = [effect]
        assert len(effects) == 1

    def test_feedback_received_event_fields(self) -> None:
        event = FeedbackReceivedEvent(
            issue_id="issue-1",
            feedback_context="User said: use REST API",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert event.issue_id == "issue-1"
        assert event.feedback_context == "User said: use REST API"
        assert event.timestamp == "2026-01-01T00:00:00Z"

    def test_feedback_received_event_is_event(self) -> None:
        event = FeedbackReceivedEvent(
            issue_id="issue-1",
            feedback_context="answer",
            timestamp="2026-01-01T00:00:00Z",
        )
        events: list[Event] = [event]
        assert len(events) == 1
