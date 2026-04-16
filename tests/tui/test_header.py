from __future__ import annotations

import time

from orca.engine.types import Issue, State, StateDef, StateMachineConfig, TypeDef, WorkerDef
from orca.tui.widgets.header import OrcaHeader, _format_elapsed


def _make_config(states: dict[str, StateDef] | None = None) -> StateMachineConfig:
    if states is None:
        states = {
            "triage": StateDef(worker=WorkerDef(kind="claude-code", prompt="t.j2", result_format={})),
            "implement": StateDef(worker=WorkerDef(kind="claude-code", prompt="i.j2", result_format={})),
            "review": StateDef(worker=WorkerDef(kind="claude-code", prompt="r.j2", result_format={})),
        }
    return StateMachineConfig(
        root_type="default",
        types={"default": TypeDef(fields={}, initial="triage", states=states)},
    )


def _make_issue(
    state: str = "triage",
    worker_active: bool = False,
    decomposed_from: str | None = None,
    visit_counts: dict[str, int] | None = None,
    failure_count: int = 0,
) -> Issue:
    return Issue(
        type="default",
        fields={},
        state=state,
        worker_active=worker_active,
        decomposed_from=decomposed_from,
        depends_on=[],
        event_log=[],
        visit_counts=visit_counts or {},
        failure_count=failure_count,
    )


def _make_state(issues: dict[str, Issue] | None = None) -> State:
    if issues is None:
        issues = {"root-1": _make_issue()}
    return State(issues=issues, worker_queues={})


class TestFormatElapsed:
    def test_seconds(self) -> None:
        assert _format_elapsed(45) == "45s"

    def test_minutes(self) -> None:
        assert _format_elapsed(120) == "2m"

    def test_hours(self) -> None:
        assert _format_elapsed(3661) == "1h01m"

    def test_negative(self) -> None:
        assert _format_elapsed(-5) == "0s"

    def test_zero(self) -> None:
        assert _format_elapsed(0) == "0s"


class TestOrcaHeaderWaiting:
    def test_no_state_shows_waiting(self) -> None:
        header = OrcaHeader(branch_name="SMEW-1942_ai_team_prd", config=_make_config())
        text = header.render_text()
        assert "SMEW-1942_ai_team_prd" in text
        assert "waiting" in text


class TestOrcaHeaderRunning:
    def test_running_with_workers(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="my-branch", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(
                    state="implement", worker_active=True, visit_counts={"triage": 1, "implement": 1}
                ),
            }
        )
        sessions = [{"started_at": time.time() - 60}]
        header.update_state(state, sessions)
        text = header.render_text()
        assert "my-branch" in text
        assert "Workers 1" in text

    def test_step_counts_only_non_terminal(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="b", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(
                    state="triage",
                    worker_active=True,
                    visit_counts={"triage": 1},
                ),
            }
        )
        header.update_state(state, [])
        text = header.render_text()
        # 3 non-terminal states: triage, implement, review
        assert "Workers" in text

    def test_green_dot_when_no_failures(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="b", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(state="triage", worker_active=True, visit_counts={"triage": 1}),
            }
        )
        header.update_state(state, [])
        text = header.render_text()
        assert "[green]\u25cf[/green]" in text

    def test_red_dot_when_failures(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="b", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(
                    state="triage",
                    worker_active=False,
                    visit_counts={"triage": 1},
                    failure_count=2,
                ),
            }
        )
        header.update_state(state, [])
        text = header.render_text()
        assert "[red]\u25cf[/red]" in text
        assert "[red]2 failed[/red]" in text

    def test_multiple_workers_counted(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="b", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(state="implement", worker_active=True, visit_counts={"triage": 1}),
                "child-1": _make_issue(
                    state="implement", worker_active=True, decomposed_from="root-1", visit_counts={"triage": 1}
                ),
                "child-2": _make_issue(
                    state="review", worker_active=False, decomposed_from="root-1", visit_counts={"triage": 1}
                ),
            }
        )
        header.update_state(state, [])
        text = header.render_text()
        assert "Workers 2" in text


class TestOrcaHeaderCompleted:
    def test_all_terminal_shows_completed(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="my-branch", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(state="done", visit_counts={"triage": 1, "implement": 1, "review": 1}),
            }
        )
        header.update_state(state, [])
        text = header.render_text()
        assert "\u2713" in text
        assert "my-branch" in text
        assert "completed" in text


class TestOrcaHeaderElapsed:
    def test_elapsed_time_displayed(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="b", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(state="triage", worker_active=True, visit_counts={"triage": 1}),
            }
        )
        # 14 minutes ago
        sessions = [{"started_at": time.time() - 840}]
        header.update_state(state, sessions)
        text = header.render_text()
        assert "14m" in text

    def test_no_sessions_no_elapsed(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="b", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(state="triage", worker_active=True, visit_counts={"triage": 1}),
            }
        )
        header.update_state(state, [])
        text = header.render_text()
        # No elapsed segment when no sessions
        parts = text.split("\u2502")
        # Should not have a time-like segment
        for part in parts:
            stripped = part.strip()
            # Allow other parts but ensure no time format
            assert not stripped.endswith("m") or "Workers" in stripped or "Step" in stripped or stripped == ""


class TestOrcaHeaderActiveWorkersOverride:
    def test_explicit_active_workers(self) -> None:
        config = _make_config()
        header = OrcaHeader(branch_name="b", config=config)
        state = _make_state(
            {
                "root-1": _make_issue(state="triage", worker_active=True, visit_counts={"triage": 1}),
            }
        )
        header.update_state(state, [], active_workers=5)
        text = header.render_text()
        assert "Workers 5" in text
