from __future__ import annotations

import json
import time
from pathlib import Path

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.state_reader import StateReader


def _make_state(title: str = "Test Issue") -> State:
    return State(
        issues={
            "issue-1": Issue(
                type="default",
                fields={"title": title, "description": "A test issue"},
                state="triage",
                worker_active=False,
                decomposed_from=None,
                depends_on=[],
                event_log=[
                    EventLogEntry(
                        timestamp="2026-01-01T00:00:00+00:00",
                        type="created",
                        data={},
                    )
                ],
            )
        },
        worker_queues={},
    )


def _write_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


class TestStateReader:
    def test_read_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        reader = StateReader(tmp_path / "nonexistent")
        assert reader.read() is None

    def test_read_returns_state_when_file_exists(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        state = _make_state()
        _write_state(run_dir / "state.json", state)
        reader = StateReader(run_dir)
        result = reader.read()
        assert result is not None
        read_state, sessions = result
        assert "issue-1" in read_state.issues
        assert read_state.issues["issue-1"].fields["title"] == "Test Issue"
        assert sessions == []

    def test_read_returns_none_when_mtime_unchanged(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())
        reader = StateReader(run_dir)
        first = reader.read()
        assert first is not None
        second = reader.read()
        assert second is None

    def test_read_returns_new_state_after_file_update(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        state_path = run_dir / "state.json"
        _write_state(state_path, _make_state("Original"))
        reader = StateReader(run_dir)
        first = reader.read()
        assert first is not None
        time.sleep(0.05)
        _write_state(state_path, _make_state("Updated"))
        result = reader.read()
        assert result is not None
        read_state, _ = result
        assert read_state.issues["issue-1"].fields["title"] == "Updated"

    def test_last_mtime_returns_zero_when_no_file(self, tmp_path: Path) -> None:
        reader = StateReader(tmp_path / "nonexistent")
        assert reader.last_mtime == 0.0

    def test_last_mtime_updates_after_read(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())
        reader = StateReader(run_dir)
        assert reader.last_mtime == 0.0
        reader.read()
        assert reader.last_mtime > 0.0

    def test_reset_allows_re_read(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())
        reader = StateReader(run_dir)
        first = reader.read()
        assert first is not None
        second = reader.read()
        assert second is None
        reader.reset()
        third = reader.read()
        assert third is not None

    def test_reads_sessions(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())
        sessions_path = run_dir / "sessions.json"
        sessions_path.write_text(json.dumps([{"issue_id": "issue-1", "state": "scoping", "session_id": "s1"}]))
        reader = StateReader(run_dir)
        result = reader.read()
        assert result is not None
        _, sessions = result
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "s1"
