"""Unit tests for _compact_run's must_surface_to_user one-shot semantics.

The daemon must emit `must_surface_to_user` only on the FIRST compact-run poll
after a new debug pause appears. On subsequent polls while the same pause is
still pending, the field must be absent so the supervising agent stays in its
polling loop (and can engage with inline comments via orca_list_pending_comments
instead of ending its turn).
"""

from __future__ import annotations

from types import SimpleNamespace

from orca.daemon.http_api import _compact_run
from orca.engine.types import Issue


def _make_issue(*, debug_pending: bool, agent_surfaced_at: float | None = None) -> Issue:
    return Issue(
        type="task",
        fields={"title": "demo"},
        state="implementing",
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
        debug_pending=debug_pending,
        agent_surfaced_at=agent_surfaced_at,
    )


def _state_dict_from_issues(issues: dict[str, Issue]) -> dict[str, object]:
    return {"issues": {iid: iss.to_dict() for iid, iss in issues.items()}}


def _fake_run_info(issues: dict[str, Issue]) -> SimpleNamespace:
    return SimpleNamespace(
        orchestrator=SimpleNamespace(state=SimpleNamespace(issues=issues)),
        status=SimpleNamespace(value="running"),
    )


def test_must_surface_present_on_first_poll() -> None:
    issue = _make_issue(debug_pending=True, agent_surfaced_at=None)
    issues = {"i1": issue}
    state_dict = _state_dict_from_issues(issues)
    run_info = _fake_run_info(issues)

    result = _compact_run("repo:branch", state_dict, run_info, sessions=[], browser_port=8888)

    assert "must_surface_to_user" in result
    assert "Paused for debug review" in result["must_surface_to_user"]
    assert "continue polling silently" in result["must_surface_to_user"]
    assert issue.agent_surfaced_at is not None  # marked surfaced as a side effect


def test_must_surface_absent_on_second_poll_same_pause() -> None:
    issue = _make_issue(debug_pending=True, agent_surfaced_at=None)
    issues = {"i1": issue}
    state_dict = _state_dict_from_issues(issues)
    run_info = _fake_run_info(issues)

    # First poll surfaces.
    first = _compact_run("repo:branch", state_dict, run_info, sessions=[], browser_port=8888)
    assert "must_surface_to_user" in first

    # Second poll while same pause still pending: field must be gone, but
    # debug_reviews stays populated so the agent knows the pause is still live.
    second = _compact_run("repo:branch", state_dict, run_info, sessions=[], browser_port=8888)
    assert "must_surface_to_user" not in second
    assert len(second["debug_reviews"]) == 1
    assert second["debug_reviews"][0]["issue_id"] == "i1"


def test_must_surface_re_emits_for_new_pause_after_resolution() -> None:
    # A new pause begins (debug_pending=True, agent_surfaced_at reset to None
    # by the reducer's _handle_worker_result for run_debug).
    issue = _make_issue(debug_pending=True, agent_surfaced_at=None)
    issues = {"i1": issue}
    state_dict = _state_dict_from_issues(issues)
    run_info = _fake_run_info(issues)

    first = _compact_run("repo:branch", state_dict, run_info, sessions=[], browser_port=8888)
    assert "must_surface_to_user" in first

    # Simulate pause resolved, then a brand new pause: agent_surfaced_at reset.
    issue.agent_surfaced_at = None

    re_surfaced = _compact_run("repo:branch", state_dict, run_info, sessions=[], browser_port=8888)
    assert "must_surface_to_user" in re_surfaced


def test_no_must_surface_when_no_debug_pause() -> None:
    issue = _make_issue(debug_pending=False)
    issues = {"i1": issue}
    state_dict = _state_dict_from_issues(issues)
    run_info = _fake_run_info(issues)

    result = _compact_run("repo:branch", state_dict, run_info, sessions=[], browser_port=8888)

    assert "must_surface_to_user" not in result
    assert result["debug_reviews"] == []
