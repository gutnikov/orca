"""Decomposition scenario tests with DAG dependencies."""

from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    Effect,
    ErrorEffect,
    State,
    StateMachineConfig,
    WorkerResultEvent,
)

DECOMPOSE_CONFIG_YAML = """\
issue:
  fields:
    title: {type: string, description: "Title"}
    text: {type: string, description: "Text"}
initial: todo
states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values: [scope]
          description: "Decision"
          values_description:
            scope: "Begin scoping"
    on:
      scope: scoping
  scoping:
    worker:
      result_format:
        outcome:
          type: enum
          values: [ready, decompose]
          description: "Scope"
          values_description:
            ready: "Ready"
            decompose: "Split"
        sub_issues:
          type: list
          required_when:
            - decompose
          items: "$issue"
          description: "Sub-issues"
    on:
      ready: implementing
      decompose:
        action: decompose
  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Result"
          values_description:
            done: "Complete"
    on:
      done: done
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


def _advance_to_scoping(
    config: StateMachineConfig, state: State, issue_id: str, gen: Callable[[], str]
) -> tuple[State, list[Effect]]:
    """Advance an issue from todo to scoping via worker result."""
    result: tuple[State, list[Effect]] = reduce(
        config, state, WorkerResultEvent(issue_id=issue_id, result={"outcome": "scope"}), gen
    )
    return result


def _complete_child(config: StateMachineConfig, state: State, child_id: str, gen: Callable[[], str]) -> State:
    """Take a child through todo→scoping(ready)→implementing→done."""
    # Child starts in todo (active, auto-dispatched). Move to scoping.
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "scope"}), gen)
    # Scoping says ready → implementing
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "ready"}), gen)
    # Implementing done → done
    state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "done"}), gen)
    return state


class TestSingleLevelDecomposeAndUnblock:
    """Root decomposes into 2 children. Both complete. Parent unblocks."""

    def test_single_level_decompose_and_unblock(self) -> None:
        config = parse_config(DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # Create root and advance to scoping
        state, _ = reduce(config, state, CreateEvent(issue_id="ROOT", fields={"title": "Root"}), gen)
        state, _ = _advance_to_scoping(config, state, "ROOT", gen)

        # Decompose into 2 children
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="ROOT",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "child-a", "fields": {"title": "Child A"}},
                        {"key": "child-b", "fields": {"title": "Child B"}},
                    ],
                },
            ),
            gen,
        )

        # Children created with generated IDs
        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "ROOT"]
        assert len(child_ids) == 2

        # Children are in todo (active state), auto-dispatched
        for cid in child_ids:
            assert state.issues[cid].state == "todo"
            assert state.issues[cid].worker_active is True

        # Root is blocked (children not terminal)
        assert state.issues["ROOT"].worker_active is False

        # Complete both children
        for cid in child_ids:
            state = _complete_child(config, state, cid, gen)
            assert state.issues[cid].state == "done"

        # After last child completes, parent gets re-dispatched in scoping
        assert state.issues["ROOT"].worker_active is True
        assert state.issues["ROOT"].state == "scoping"

        # Parent returns ready → implementing
        state, effects = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result={"outcome": "ready"}), gen)
        assert state.issues["ROOT"].state == "implementing"
        assert state.issues["ROOT"].worker_active is True

        # Implementing done
        state, _ = reduce(config, state, WorkerResultEvent(issue_id="ROOT", result={"outcome": "done"}), gen)
        assert state.issues["ROOT"].state == "done"


class TestThreeLevelCascadingUnblock:
    """L1 decomposes → L2 decomposes → L3. Cascading unblock."""

    def test_three_level_cascading_unblock(self) -> None:
        config = parse_config(DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        # L1: create and decompose
        state, _ = reduce(config, state, CreateEvent(issue_id="L1", fields={"title": "Level 1"}), gen)
        state, _ = _advance_to_scoping(config, state, "L1", gen)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="L1",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "l2", "fields": {"title": "Level 2"}}],
                },
            ),
            gen,
        )

        l2_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "L1"]
        assert len(l2_ids) == 1
        l2_id = l2_ids[0]

        # L2: in todo (active, auto-dispatched), move to scoping
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=l2_id, result={"outcome": "scope"}), gen)
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id=l2_id,
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "l3", "fields": {"title": "Level 3"}}],
                },
            ),
            gen,
        )

        l3_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == l2_id]
        assert len(l3_ids) == 1
        l3_id = l3_ids[0]

        # L3: complete
        state = _complete_child(config, state, l3_id, gen)
        assert state.issues[l3_id].state == "done"

        # L2 should be unblocked and re-dispatched in scoping
        assert state.issues[l2_id].worker_active is True
        assert state.issues[l2_id].state == "scoping"

        # L2: ready → implementing → done
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=l2_id, result={"outcome": "ready"}), gen)
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=l2_id, result={"outcome": "done"}), gen)
        assert state.issues[l2_id].state == "done"

        # L1 should be unblocked and re-dispatched in scoping
        assert state.issues["L1"].worker_active is True
        assert state.issues["L1"].state == "scoping"


class TestEmptyDecomposeError:
    """Worker returns decompose with empty sub_issues → ErrorEffect."""

    def test_empty_decompose_error(self) -> None:
        config = parse_config(DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        state, _ = reduce(config, state, CreateEvent(issue_id="ROOT", fields={"title": "Root"}), gen)
        state, _ = _advance_to_scoping(config, state, "ROOT", gen)

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="ROOT",
                result={"outcome": "decompose", "sub_issues": []},
            ),
            gen,
        )

        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "non-empty" in effects[0].message.lower() or "empty" in effects[0].message.lower()
        # State should be unchanged
        assert state.issues["ROOT"].state == "scoping"
        assert state.issues["ROOT"].worker_active is True


class TestMassiveFanOut:
    """Decompose into 20 children. All complete. Parent unblocks."""

    def test_massive_fan_out(self) -> None:
        config = parse_config(DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        state, _ = reduce(config, state, CreateEvent(issue_id="ROOT", fields={"title": "Root"}), gen)
        state, _ = _advance_to_scoping(config, state, "ROOT", gen)

        sub_issues = [{"key": f"child-{i}", "fields": {"title": f"Child {i}"}} for i in range(20)]
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="ROOT",
                result={"outcome": "decompose", "sub_issues": sub_issues},
            ),
            gen,
        )

        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "ROOT"]
        assert len(child_ids) == 20

        # Complete all children
        for cid in child_ids:
            state = _complete_child(config, state, cid, gen)

        # Parent should be unblocked
        assert state.issues["ROOT"].worker_active is True
        assert state.issues["ROOT"].state == "scoping"


class TestDiamondDependency:
    """Decompose with diamond: db(no deps), users(depends_on:[db]), orders(depends_on:[db])."""

    def test_diamond_dependency(self) -> None:
        config = parse_config(DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        state, _ = reduce(config, state, CreateEvent(issue_id="ROOT", fields={"title": "Root"}), gen)
        state, _ = _advance_to_scoping(config, state, "ROOT", gen)

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="ROOT",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "db", "fields": {"title": "DB Migration"}, "depends_on": []},
                        {"key": "users", "fields": {"title": "Users Service"}, "depends_on": ["db"]},
                        {"key": "orders", "fields": {"title": "Orders Service"}, "depends_on": ["db"]},
                    ],
                },
            ),
            gen,
        )

        # Find the real IDs
        child_ids = {iss.fields["title"]: iid for iid, iss in state.issues.items() if iss.decomposed_from == "ROOT"}
        db_id = child_ids["DB Migration"]
        users_id = child_ids["Users Service"]
        orders_id = child_ids["Orders Service"]

        # db has no depends_on, users and orders depend on db
        assert state.issues[db_id].depends_on == []
        assert state.issues[users_id].depends_on == [db_id]
        assert state.issues[orders_id].depends_on == [db_id]

        # db should be auto-dispatched in todo (not blocked)
        assert state.issues[db_id].worker_active is True
        assert state.issues[db_id].state == "todo"

        # users and orders should NOT be dispatched (blocked by db dependency)
        assert state.issues[users_id].worker_active is False
        assert state.issues[orders_id].worker_active is False

        # Verify dispatch effects: only db should have been dispatched
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        dispatched_ids = {e.issue_id for e in dispatch_effects}
        assert db_id in dispatched_ids
        assert users_id not in dispatched_ids
        assert orders_id not in dispatched_ids

        # Complete db through todo→scoping→implementing→done
        state = _complete_child(config, state, db_id, gen)
        assert state.issues[db_id].state == "done"

        # After db completes, users and orders should be auto-dispatched via cascading unblock
        assert state.issues[users_id].worker_active is True
        assert state.issues[orders_id].worker_active is True


class TestDispatchIncludesChildrenContext:
    """After unblock, DispatchWorkerEffect includes resolved children context."""

    def test_dispatch_includes_children_context(self) -> None:
        config = parse_config(DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        state, _ = reduce(config, state, CreateEvent(issue_id="ROOT", fields={"title": "Root"}), gen)
        state, _ = _advance_to_scoping(config, state, "ROOT", gen)

        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="ROOT",
                result={
                    "outcome": "decompose",
                    "sub_issues": [
                        {"key": "c1", "fields": {"title": "Child 1"}},
                    ],
                },
            ),
            gen,
        )

        child_ids = [iid for iid, iss in state.issues.items() if iss.decomposed_from == "ROOT"]
        assert len(child_ids) == 1
        child_id = child_ids[0]

        # Complete the child (todo→scoping→implementing→done) — last step triggers parent re-dispatch
        # Child is auto-dispatched in todo
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "scope"}), gen)
        state, _ = reduce(config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "ready"}), gen)
        state, effects_from_last = reduce(
            config, state, WorkerResultEvent(issue_id=child_id, result={"outcome": "done"}), gen
        )

        # The last step should produce a dispatch for the parent
        parent_dispatches = [
            e for e in effects_from_last if isinstance(e, DispatchWorkerEffect) and e.issue_id == "ROOT"
        ]
        assert len(parent_dispatches) == 1
        dispatch = parent_dispatches[0]

        # The issue context should include children
        assert "children" in dispatch.issue
        assert len(dispatch.issue["children"]) == 1
        child_context = dispatch.issue["children"][0]
        assert child_context["issue_id"] == child_id
        assert child_context["state"] == "done"
        assert len(child_context["result_history"]) > 0


class TestBlockedIssueRejectsWorkerResult:
    """Send WorkerResult to a decomposition-blocked parent → ErrorEffect."""

    def test_blocked_issue_rejects_worker_result(self) -> None:
        config = parse_config(DECOMPOSE_CONFIG_YAML)
        gen = _counter()
        state = _empty_state()

        state, _ = reduce(config, state, CreateEvent(issue_id="ROOT", fields={"title": "Root"}), gen)
        state, _ = _advance_to_scoping(config, state, "ROOT", gen)

        # Decompose
        state, _ = reduce(
            config,
            state,
            WorkerResultEvent(
                issue_id="ROOT",
                result={
                    "outcome": "decompose",
                    "sub_issues": [{"key": "c1", "fields": {"title": "Child 1"}}],
                },
            ),
            gen,
        )

        # Parent is now blocked. Try to send a worker result to it.
        # Parent's worker_active is False after decompose, so this should error
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="ROOT", result={"outcome": "ready"}),
            gen,
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
