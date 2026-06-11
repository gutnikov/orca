from __future__ import annotations

import json
from pathlib import Path

import pytest

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.app import OrcaApp, _select_daemon_run_id
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

    def test_session_result_map_uses_debug_review_snapshots(self, tmp_path: Path) -> None:
        issue = Issue(
            type="default",
            fields={"title": "Root"},
            state="done",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[
                EventLogEntry("2026-01-01T00:00:00+00:00", "created", {"state": "preflight"}),
                EventLogEntry("2026-01-01T00:00:01+00:00", "worker_result", {"outcome": "ready"}),
                EventLogEntry(
                    "2026-01-01T00:00:02+00:00",
                    "debug_review_required",
                    {"snapshot": {"worker_result": {"outcome": "ready", "summary": "preflight"}}},
                ),
                EventLogEntry("2026-01-01T00:00:03+00:00", "debug_decision", {"action": "accept"}),
                EventLogEntry("2026-01-01T00:00:04+00:00", "worker_result", {"outcome": "ready"}),
                EventLogEntry(
                    "2026-01-01T00:00:05+00:00",
                    "transitioned",
                    {"from": "preflight", "to": "implementing"},
                ),
                EventLogEntry("2026-01-01T00:00:06+00:00", "worker_result", {"outcome": "done"}),
                EventLogEntry(
                    "2026-01-01T00:00:07+00:00",
                    "debug_review_required",
                    {"snapshot": {"worker_result": {"outcome": "done", "summary": "implementing"}}},
                ),
                EventLogEntry("2026-01-01T00:00:08+00:00", "debug_decision", {"action": "accept"}),
                EventLogEntry("2026-01-01T00:00:09+00:00", "worker_result", {"outcome": "done"}),
            ],
        )
        app = OrcaApp(run_dir=tmp_path / "run", branch_name="test-branch")
        app._state = State(issues={"root-1": issue}, worker_queues={})
        app._sessions = [
            {
                "session_id": "session-preflight",
                "issue_id": "root-1",
                "state": "preflight",
                "started_at": "2026-01-01T00:00:00+00:00",
                "completed_at": "2026-01-01T00:00:04+00:00",
            },
            {
                "session_id": "session-implementing",
                "issue_id": "root-1",
                "state": "implementing",
                "started_at": "2026-01-01T00:00:05+00:00",
                "completed_at": "2026-01-01T00:00:09+00:00",
            },
        ]

        result_map = app._session_result_map("root-1")

        assert result_map["session-preflight"]["summary"] == "preflight"
        assert result_map["session-implementing"]["summary"] == "implementing"


class TestDaemonUnreachable:
    @pytest.mark.asyncio
    async def test_unreachable_daemon_sets_subtitle_instead_of_crashing(self, tmp_path: Path) -> None:
        class _UnreachableReader:
            unreachable = True

            async def read(self) -> None:
                return None

        app = OrcaApp(run_dir=tmp_path / "run", branch_name="test-branch")
        async with app.run_test() as pilot:
            app._daemon_reader = _UnreachableReader()  # type: ignore[assignment]
            await app._poll_daemon_state()
            await pilot.pause()
            assert app.sub_title == "daemon unreachable"


class TestDaemonRunSelection:
    def test_selects_requested_run_id(self) -> None:
        runs = [
            {"run_id": "branch-a:default", "status": "running"},
            {"run_id": "branch-b:default", "status": "running"},
        ]

        assert _select_daemon_run_id(runs, requested_run_id="branch-b:default") == "branch-b:default"

    def test_requested_run_id_must_exist(self) -> None:
        with pytest.raises(ValueError, match="run 'missing:default' not found"):
            _select_daemon_run_id([{"run_id": "branch-a:default", "status": "running"}], "missing:default")

    def test_defaults_to_first_running_run(self) -> None:
        runs = [
            {"run_id": "branch-a:default", "status": "failed"},
            {"run_id": "branch-b:default", "status": "running"},
        ]

        assert _select_daemon_run_id(runs) == "branch-b:default"

    def test_falls_back_to_first_run(self) -> None:
        runs = [
            {"run_id": "branch-a:default", "status": "completed"},
            {"run_id": "branch-b:default", "status": "failed"},
        ]

        assert _select_daemon_run_id(runs) == "branch-a:default"
