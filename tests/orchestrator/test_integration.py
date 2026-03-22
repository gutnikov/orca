from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orca.engine import parse_config, reduce
from orca.engine.types import CreateEvent, DispatchWorkerEffect, State
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.worker import WorkerFailure, WorkerOutcome, WorkerSuccess


class ScriptedWorker:
    """Worker that consumes scripted outcomes in order per (issue_id, state) key."""

    def __init__(self, script: list[tuple[tuple[str, str], WorkerOutcome]]) -> None:
        self.script = list(script)  # ordered, consumed in order per key
        self.calls: list[tuple[str, str]] = []

    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
    ) -> WorkerOutcome:
        key = (effect.issue_id, effect.state)
        self.calls.append(key)
        for i, (k, outcome) in enumerate(self.script):
            if k == key:
                self.script.pop(i)
                return outcome
        return WorkerFailure(error=f"no script for {key}")


def _counter(start: int = 0) -> Any:
    n = start

    def gen() -> str:
        nonlocal n
        n += 1
        return f"issue-{n}"

    return gen


def _now() -> str:
    return "2026-01-01T00:00:00Z"


DECOMPOSE_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: Title
states:
  planning:
    worker:
      kind: claude-code
      prompt: prompts/plan.md
      result_format:
        outcome:
          type: enum
          values: [decompose, implement]
          description: Planning outcome
        sub_issues:
          type: list
          items: "$issue"
          description: Sub-tasks
          required_when: [decompose]
    on:
      decompose:
        action: decompose
      implement: implementing
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/impl.md
      result_format:
        outcome:
          type: enum
          values: [done]
          description: Outcome
    on:
      done: done
  done:
    terminal: true
initial: planning
"""


@pytest.mark.asyncio()
class TestIntegrationDecompose:
    async def test_decompose_and_complete(self, tmp_path: Path) -> None:
        """Full end-to-end test of decompose workflow:
        1. Root issue-1 decomposes into issue-2 (db) and issue-3 (api, depends on db)
        2. issue-2 completes (planning -> implementing -> done)
        3. issue-3 unblocked, completes (planning -> implementing -> done)
        4. Root issue-1 unblocked, completes (planning -> implementing -> done)
        """
        config = parse_config(DECOMPOSE_CONFIG)
        state = State(issues={}, worker_queues={})

        # Create root issue; counter starts at 1 so root = issue-1
        gen_id = _counter(start=1)
        create_event = CreateEvent(issue_id="issue-1", fields={"title": "Root"}, timestamp=_now())
        state, initial_effects = reduce(config, state, create_event, gen_id, _now)

        # Sub-issue IDs: decompose will call gen_id twice -> issue-2, issue-3
        # issue-2 = db (no deps), issue-3 = api (depends_on ["db"] key, resolved to issue-2)

        persistence = Persistence(tmp_path, "main")
        persistence.save(state)

        branches = BranchMap(tmp_path, "main")

        worker = ScriptedWorker(
            script=[
                # Root issue-1 in planning: first call -> decompose into two sub-issues
                (
                    ("issue-1", "planning"),
                    WorkerSuccess(
                        result={
                            "outcome": "decompose",
                            "sub_issues": [
                                {"key": "db", "fields": {"title": "DB task"}},
                                {"key": "api", "fields": {"title": "API task"}, "depends_on": ["db"]},
                            ],
                        }
                    ),
                ),
                # issue-2 (db) in planning -> implement
                (("issue-2", "planning"), WorkerSuccess(result={"outcome": "implement"})),
                # issue-2 (db) in implementing -> done
                (("issue-2", "implementing"), WorkerSuccess(result={"outcome": "done"})),
                # issue-3 (api) unblocked after db done, planning -> implement
                (("issue-3", "planning"), WorkerSuccess(result={"outcome": "implement"})),
                # issue-3 (api) in implementing -> done
                (("issue-3", "implementing"), WorkerSuccess(result={"outcome": "done"})),
                # Root issue-1 unblocked after all children done, planning -> implement (second call)
                (("issue-1", "planning"), WorkerSuccess(result={"outcome": "implement"})),
                # Root issue-1 in implementing -> done
                (("issue-1", "implementing"), WorkerSuccess(result={"outcome": "done"})),
            ]
        )

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=persistence,
            branches=branches,
            workers={"claude-code": worker},
            generate_id=gen_id,
            now=_now,
            worktree_resolver=lambda iid: tmp_path,
        )

        await orchestrator.run("issue-1", initial_effects)

        final_state = orchestrator.state

        # Root issue must be terminal
        assert "issue-1" in final_state.issues
        assert final_state.issues["issue-1"].state == "done"

        # Sub-issues must also be terminal
        assert "issue-2" in final_state.issues
        assert final_state.issues["issue-2"].state == "done"

        assert "issue-3" in final_state.issues
        assert final_state.issues["issue-3"].state == "done"

        # Verify the full call sequence
        assert worker.calls == [
            ("issue-1", "planning"),  # decompose
            ("issue-2", "planning"),  # db: implement
            ("issue-2", "implementing"),  # db: done
            ("issue-3", "planning"),  # api: implement (unblocked after db)
            ("issue-3", "implementing"),  # api: done
            ("issue-1", "planning"),  # root: implement (unblocked after all children)
            ("issue-1", "implementing"),  # root: done
        ]
