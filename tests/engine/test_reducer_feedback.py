from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchFeedbackAgentEffect,
    DispatchWorkerEffect,
    ErrorEffect,
    FeedbackReceivedEvent,
    State,
    WorkerResultEvent,
)


def _counter() -> Callable[[], str]:
    n = 0

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"id-{n}"

    return next_id


def _clock(value: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: value


def _setup(yaml: str, max_retries: int | None = 3) -> tuple[object, State]:
    """Create config and state with one issue in initial state with worker_active=True."""
    from orca.engine.types import StateMachineConfig

    config = parse_config(yaml)
    assert isinstance(config, StateMachineConfig)
    if max_retries is not None:
        object.__setattr__(config, "max_worker_retries", max_retries)
    state = State(issues={}, worker_queues={})
    state, _ = reduce(
        config,
        state,
        CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="2026-01-01T00:00:00Z"),
        _counter(),
        _clock(),
    )
    return config, state


class TestNeedsFeedbackOutcome:
    def test_needs_feedback_emits_dispatch_feedback_effect(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        assert state.issues["A"].worker_active is True

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Which API?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        feedback_effects = [e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]
        assert len(feedback_effects) == 1
        assert feedback_effects[0].issue_id == "A"
        assert feedback_effects[0].questions == "Which API?"
        assert feedback_effects[0].state == "implementing"

    def test_needs_feedback_clears_worker_active(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )
        assert state.issues["A"].worker_active is False

    def test_needs_feedback_increments_failure_count(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        assert state.issues["A"].failure_count == 0

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )
        assert state.issues["A"].failure_count == 1

    def test_needs_feedback_stores_questions_in_fields(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Which API?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )
        assert state.issues["A"].fields["feedback_questions"] == "Which API?"

    def test_needs_feedback_logs_worker_result(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )
        result_entries = [e for e in state.issues["A"].event_log if e.type == "worker_result"]
        assert len(result_entries) == 1
        assert result_entries[0].data["outcome"] == "needs_feedback"

    def test_needs_feedback_exhausted_retries_emits_error(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state.issues["A"].failure_count = 2  # max is 3, will become 3

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )

        feedback_effects = [e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]
        assert len(feedback_effects) == 0
        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1
        assert "retries exhausted" in error_effects[0].message

    def test_needs_feedback_does_not_change_state(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )
        assert state.issues["A"].state == "implementing"


class TestFeedbackReceivedEvent:
    def test_feedback_received_stores_context_and_redispatches(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        # Worker returns needs_feedback
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )
        assert state.issues["A"].worker_active is False

        # Feedback received
        state, effects = reduce(
            config,
            state,
            FeedbackReceivedEvent(
                issue_id="A", feedback_context="User said: use REST", timestamp="2026-01-01T00:02:00Z"
            ),
            _counter(),
            _clock(),
        )

        assert state.issues["A"].fields["feedback_context"] == "User said: use REST"
        assert state.issues["A"].worker_active is True
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1
        assert dispatch_effects[0].issue_id == "A"
        assert dispatch_effects[0].state == "implementing"

    def test_feedback_received_logs_event(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q?"},
                timestamp="2026-01-01T00:01:00Z",
            ),
            _counter(),
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            FeedbackReceivedEvent(issue_id="A", feedback_context="answer", timestamp="2026-01-01T00:02:00Z"),
            _counter(),
            _clock(),
        )

        fb_entries = [e for e in state.issues["A"].event_log if e.type == "feedback_received"]
        assert len(fb_entries) == 1

    def test_feedback_received_nonexistent_issue_emits_error(self, feedback_config_yaml: str) -> None:
        config = parse_config(feedback_config_yaml)
        state = State(issues={}, worker_queues={})

        state, effects = reduce(
            config,
            state,
            FeedbackReceivedEvent(issue_id="NOPE", feedback_context="answer", timestamp="2026-01-01T00:02:00Z"),
            _counter(),
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1

    def test_feedback_received_when_worker_active_emits_error(self, feedback_config_yaml: str) -> None:
        config, state = _setup(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        assert state.issues["A"].worker_active is True

        state, effects = reduce(
            config,
            state,
            FeedbackReceivedEvent(issue_id="A", feedback_context="answer", timestamp="2026-01-01T00:02:00Z"),
            _counter(),
            _clock(),
        )

        error_effects = [e for e in effects if isinstance(e, ErrorEffect)]
        assert len(error_effects) == 1


class TestFeedbackRoundTrip:
    """End-to-end: worker -> needs_feedback -> feedback_received -> re-dispatch -> complete."""

    def test_full_feedback_then_complete(self, feedback_config_yaml: str) -> None:
        config = parse_config(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        object.__setattr__(config, "max_worker_retries", 3)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # 1. Create issue — worker dispatched in implementing
        state, effects = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "implementing"
        assert state.issues["A"].worker_active is True

        # 2. Worker returns needs_feedback
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "REST or gRPC?"},
                timestamp="t1",
            ),
            gen,
            _clock(),
        )
        assert state.issues["A"].worker_active is False
        assert state.issues["A"].failure_count == 1
        assert state.issues["A"].fields["feedback_questions"] == "REST or gRPC?"
        feedback_effects = [e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]
        assert len(feedback_effects) == 1

        # 3. Feedback agent completes — user said REST
        state, effects = reduce(
            config,
            state,
            FeedbackReceivedEvent(
                issue_id="A",
                feedback_context="User: Use REST API for all new endpoints.",
                timestamp="t2",
            ),
            gen,
            _clock(),
        )
        assert state.issues["A"].worker_active is True
        assert state.issues["A"].fields["feedback_context"] == "User: Use REST API for all new endpoints."
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1

        # 4. Re-dispatched worker completes successfully
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="A", result={"outcome": "complete"}, timestamp="t3"),
            gen,
            _clock(),
        )
        assert state.issues["A"].state == "done"
        assert state.issues["A"].worker_active is False
        assert state.issues["A"].failure_count == 0  # reset on success

    def test_multiple_feedback_rounds(self, feedback_config_yaml: str) -> None:
        """Worker can request feedback multiple times (within retry budget)."""
        config = parse_config(feedback_config_yaml)
        from orca.engine.types import StateMachineConfig

        assert isinstance(config, StateMachineConfig)
        object.__setattr__(config, "max_worker_retries", 3)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )

        # Round 1: needs_feedback
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q1?"},
                timestamp="t1",
            ),
            gen,
            _clock(),
        )
        assert state.issues["A"].failure_count == 1
        assert len([e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]) == 1

        # Round 1: feedback received
        state, _ = reduce(
            config,
            state,
            FeedbackReceivedEvent(issue_id="A", feedback_context="A1", timestamp="t2"),
            gen,
            _clock(),
        )

        # Round 2: needs_feedback again
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q2?"},
                timestamp="t3",
            ),
            gen,
            _clock(),
        )
        assert state.issues["A"].failure_count == 2
        assert state.issues["A"].fields["feedback_questions"] == "Q2?"
        assert len([e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]) == 1

        # Round 2: feedback received
        state, _ = reduce(
            config,
            state,
            FeedbackReceivedEvent(issue_id="A", feedback_context="A2", timestamp="t4"),
            gen,
            _clock(),
        )

        # Round 3: needs_feedback — but this will exhaust retries (max=3)
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="A",
                result={"outcome": "needs_feedback", "feedback_questions": "Q3?"},
                timestamp="t5",
            ),
            gen,
            _clock(),
        )
        assert state.issues["A"].failure_count == 3
        # Should NOT dispatch feedback agent — retries exhausted
        assert len([e for e in effects if isinstance(e, DispatchFeedbackAgentEffect)]) == 0
        assert len([e for e in effects if isinstance(e, ErrorEffect)]) == 1
