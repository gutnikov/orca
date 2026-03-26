from __future__ import annotations

import json
from pathlib import Path

import pytest

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.app import OrcaApp
from orca.tui.widgets.issue_detail import IssueDetail
from orca.tui.widgets.issue_tree import IssueTree


def _make_state(title: str = "Root Task", state_name: str = "triage") -> State:
    return State(
        issues={
            "root-1": Issue(
                type="default",
                fields={"title": title, "description": "Root description"},
                state=state_name,
                worker_active=False,
                decomposed_from=None,
                depends_on=[],
                event_log=[
                    EventLogEntry(
                        timestamp="2026-01-01T00:00:00+00:00",
                        type="created",
                        data={"state": state_name},
                    )
                ],
            ),
        },
        worker_queues={},
    )


def _write_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


class TestOrcaApp:
    @pytest.mark.asyncio
    async def test_app_mounts_two_panels(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())

        app = OrcaApp(run_dir=run_dir, branch_name="test-branch")
        async with app.run_test() as pilot:
            await pilot.pause()

            assert len(app.query(IssueTree)) == 1
            assert len(app.query(IssueDetail)) == 1

    @pytest.mark.asyncio
    async def test_app_loads_initial_state(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state("My Root"))

        app = OrcaApp(run_dir=run_dir, branch_name="test-branch")
        async with app.run_test() as pilot:
            await pilot.pause()

            tree = app.query_one(IssueTree)
            assert len(tree.root.children) == 1
            assert "My Root" in str(tree.root.children[0].label)

    @pytest.mark.asyncio
    async def test_quit_binding(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())

        app = OrcaApp(run_dir=run_dir, branch_name="test-branch")
        async with app.run_test() as pilot:
            await pilot.press("q")
