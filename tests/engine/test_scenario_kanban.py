"""Kanban workflow scenario tests: todo → implementing → review → done."""

from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    AdvanceEvent,
    CreateEvent,
    DispatchWorkerEffect,
    State,
    WorkerResultEvent,
)

KANBAN_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
    text: {type: string, description: "Description"}
initial: todo
states:
  todo: {}
  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Result"
          values_description:
            done: "Complete"
        summary:
          type: string
          description: "What was done"
    on:
      done: review
  review:
    worker:
      result_format:
        outcome:
          type: enum
          values: [approved, rejected]
          description: "Review result"
          values_description:
            approved: "Approved"
            rejected: "Rejected"
        feedback:
          type: string
          description: "Feedback"
    on:
      approved: done
      rejected: implementing
  done:
    terminal: true
"""


def _counter() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"GEN-{n}"

    return gen


def _empty_state() -> State:
    return State(issues={}, worker_queues={})


class TestFullHappyPath:
    """Issue goes todo → implementing → review(approved) → done."""

    def test_full_happy_path(self) -> None:
        config = parse_config(KANBAN_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create issue in todo (passive state, no dispatch)
        state, effects = reduce(config, state, CreateEvent(issue_id="K-1", fields={"title": "Feature A"}), gen)
        assert state.issues["K-1"].state == "todo"
        assert state.issues["K-1"].worker_active is False
        assert effects == []

        # Advance to implementing (active state, should dispatch)
        state, effects = reduce(config, state, AdvanceEvent(issue_id="K-1", target_state="implementing"), gen)
        assert state.issues["K-1"].state == "implementing"
        assert state.issues["K-1"].worker_active is True
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "K-1"
        assert effects[0].state == "implementing"

        # Worker completes implementing → transitions to review
        state, effects = reduce(
            config, state, WorkerResultEvent(issue_id="K-1", result={"outcome": "done", "summary": "Built it"}), gen
        )
        assert state.issues["K-1"].state == "review"
        assert state.issues["K-1"].worker_active is True
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].state == "review"
        assert len(state.issues["K-1"].result_history) == 1

        # Review approves → transitions to done (terminal)
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="K-1", result={"outcome": "approved", "feedback": "LGTM"}),
            gen,
        )
        assert state.issues["K-1"].state == "done"
        assert state.issues["K-1"].worker_active is False
        assert effects == []
        assert len(state.issues["K-1"].result_history) == 2


class TestReviewRejectionLoop:
    """Issue gets rejected 2 times, approved on 3rd attempt."""

    def test_review_rejection_loop(self) -> None:
        config = parse_config(KANBAN_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create and advance to implementing
        state, _ = reduce(config, state, CreateEvent(issue_id="K-1", fields={"title": "Feature B"}), gen)
        state, _ = reduce(config, state, AdvanceEvent(issue_id="K-1", target_state="implementing"), gen)

        for attempt in range(1, 4):
            # Implementing completes → review
            state, effects = reduce(
                config,
                state,
                WorkerResultEvent(issue_id="K-1", result={"outcome": "done", "summary": f"Attempt {attempt}"}),
                gen,
            )
            assert state.issues["K-1"].state == "review"
            assert len(effects) == 1
            assert isinstance(effects[0], DispatchWorkerEffect)

            if attempt < 3:
                # Reject → back to implementing
                state, effects = reduce(
                    config,
                    state,
                    WorkerResultEvent(issue_id="K-1", result={"outcome": "rejected", "feedback": "Needs work"}),
                    gen,
                )
                assert state.issues["K-1"].state == "implementing"
                assert state.issues["K-1"].worker_active is True
                assert len(effects) == 1
                assert isinstance(effects[0], DispatchWorkerEffect)
                assert effects[0].state == "implementing"
            else:
                # Approve → done
                state, effects = reduce(
                    config,
                    state,
                    WorkerResultEvent(issue_id="K-1", result={"outcome": "approved", "feedback": "Ship it"}),
                    gen,
                )
                assert state.issues["K-1"].state == "done"

        # 3 implementing results + 2 rejected reviews + 1 approved review = 6
        assert len(state.issues["K-1"].result_history) == 6
        # Verify the pattern of states in result_history
        states_in_history = [e.state for e in state.issues["K-1"].result_history]
        assert states_in_history == [
            "implementing",
            "review",
            "implementing",
            "review",
            "implementing",
            "review",
        ]


class TestParallelIssues:
    """5 issues all in implementing simultaneously, complete in reverse order."""

    def test_parallel_issues(self) -> None:
        config = parse_config(KANBAN_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        issue_ids = [f"K-{i}" for i in range(1, 6)]

        # Create all issues and advance to implementing
        for iid in issue_ids:
            state, _ = reduce(config, state, CreateEvent(issue_id=iid, fields={"title": f"Issue {iid}"}), gen)
            state, effects = reduce(config, state, AdvanceEvent(issue_id=iid, target_state="implementing"), gen)
            assert len(effects) == 1
            assert isinstance(effects[0], DispatchWorkerEffect)

        # All 5 should be implementing with worker_active
        for iid in issue_ids:
            assert state.issues[iid].state == "implementing"
            assert state.issues[iid].worker_active is True

        # Complete in reverse order, going through full pipeline
        for iid in reversed(issue_ids):
            # implementing → review
            state, effects = reduce(
                config, state, WorkerResultEvent(issue_id=iid, result={"outcome": "done", "summary": "Done"}), gen
            )
            assert state.issues[iid].state == "review"
            assert len(effects) == 1

            # review → done
            state, effects = reduce(
                config,
                state,
                WorkerResultEvent(issue_id=iid, result={"outcome": "approved", "feedback": "OK"}),
                gen,
            )
            assert state.issues[iid].state == "done"
            assert state.issues[iid].worker_active is False

        # Verify all done, no interference
        for iid in issue_ids:
            assert state.issues[iid].state == "done"
            assert len(state.issues[iid].result_history) == 2
