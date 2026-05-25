from __future__ import annotations

from pathlib import Path as _Path

import pytest

from orca.engine.config import parse_config
from orca.engine.dispatch import (
    backfill_queue,
    build_issue_context,
    build_result_format,
    build_run_context,
    get_children,
    is_blocked,
    remove_from_queue,
    try_dispatch,
)
from orca.engine.types import (
    DispatchWorkerEffect,
    Effect,
    EnumFieldDef,
    EventLogEntry,
    FieldDef,
    Issue,
    ListFieldDef,
    State,
    StateDef,
    StateMachineConfig,
    StringFieldDef,
    TypeDef,
    WorkerDef,
)


def _make_config(
    states: dict[str, StateDef] | None = None,
    initial: str = "todo",
) -> StateMachineConfig:
    if states is None:
        states = {
            "todo": StateDef(
                worker=WorkerDef(
                    kind="claude-code",
                    prompt="prompts/default.md",
                    result_format={
                        "outcome": EnumFieldDef(values=["start"], description="Decision"),
                    },
                ),
                on={},
            ),
            "implementing": StateDef(
                worker=WorkerDef(
                    kind="claude-code",
                    prompt="prompts/default.md",
                    result_format={
                        "outcome": EnumFieldDef(values=["complete"], description="Outcome"),
                    },
                ),
                on={},
            ),
            "apply": StateDef(
                worker=WorkerDef(
                    kind="claude-code",
                    prompt="prompts/default.md",
                    result_format={
                        "outcome": EnumFieldDef(values=["applied"], description="Apply result"),
                    },
                ),
                on={},
                max_workers=1,
            ),
        }
    return StateMachineConfig(
        root_type="default",
        types={
            "default": TypeDef(
                fields={"title": FieldDef(type="string", description="Title")},
                initial=initial,
                states=states,
            )
        },
    )


def _make_issue(
    state: str = "todo",
    worker_active: bool = False,
    decomposed_from: str | None = None,
    depends_on: list[str] | None = None,
    fields: dict[str, object] | None = None,
    event_log: list[EventLogEntry] | None = None,
    visit_counts: dict[str, int] | None = None,
    hop_count: int = 0,
) -> Issue:
    return Issue(
        type="default",
        fields=fields or {"title": "Test"},
        state=state,
        worker_active=worker_active,
        decomposed_from=decomposed_from,
        depends_on=depends_on or [],
        event_log=event_log or [],
        visit_counts=visit_counts or {},
        hop_count=hop_count,
    )


class TestIsBlocked:
    def test_not_blocked_no_children_no_deps(self) -> None:
        config = _make_config()
        state = State(issues={"A": _make_issue()}, worker_queues={})
        assert is_blocked(state, config, "A") is False

    def test_blocked_non_terminal_children(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo"),
                "B": _make_issue(state="implementing", decomposed_from="A"),
            },
            worker_queues={},
        )
        assert is_blocked(state, config, "A") is True

    def test_not_blocked_all_children_terminal(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo"),
                "B": _make_issue(state="done", decomposed_from="A"),
            },
            worker_queues={},
        )
        assert is_blocked(state, config, "A") is False

    def test_blocked_non_terminal_depends_on(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo", depends_on=["B"]),
                "B": _make_issue(state="implementing"),
            },
            worker_queues={},
        )
        assert is_blocked(state, config, "A") is True

    def test_not_blocked_all_deps_terminal(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo", depends_on=["B"]),
                "B": _make_issue(state="done"),
            },
            worker_queues={},
        )
        assert is_blocked(state, config, "A") is False


class TestGetChildren:
    def test_returns_children(self) -> None:
        state = State(
            issues={
                "A": _make_issue(),
                "B": _make_issue(decomposed_from="A"),
                "C": _make_issue(decomposed_from="A"),
                "D": _make_issue(decomposed_from="B"),
            },
            worker_queues={},
        )
        children = get_children(state, "A")
        assert sorted(children) == ["B", "C"]

    def test_no_children(self) -> None:
        state = State(issues={"A": _make_issue()}, worker_queues={})
        assert get_children(state, "A") == []


class TestBuildIssueContext:
    def test_includes_resolved_children(self) -> None:
        state = State(
            issues={
                "A": _make_issue(state="todo", fields={"title": "Parent"}),
                "B": _make_issue(
                    state="done",
                    decomposed_from="A",
                    fields={"title": "Child1"},
                    event_log=[
                        EventLogEntry(
                            timestamp="2026-03-22T10:00:00Z",
                            type="worker_result",
                            data={"outcome": "complete"},
                        )
                    ],
                ),
            },
            worker_queues={},
        )
        ctx = build_issue_context(state, "A")
        assert ctx["fields"] == {"title": "Parent"}
        assert ctx["event_log"] == []
        assert ctx["decomposed_from"] is None
        assert ctx["depends_on"] == []
        assert len(ctx["children"]) == 1
        child = ctx["children"][0]
        assert child["issue_id"] == "B"
        assert child["fields"] == {"title": "Child1"}
        assert child["state"] == "done"
        assert child["event_log"] == [
            {"timestamp": "2026-03-22T10:00:00Z", "type": "worker_result", "data": {"outcome": "complete"}}
        ]


class TestBuildResultFormat:
    def test_enum_field(self) -> None:
        config = _make_config()
        result = build_result_format(config, "default", "todo")
        assert result["outcome"] == {
            "type": "enum",
            "values": ["start"],
            "description": "Decision",
            "values_description": {},
        }

    def test_string_field(self) -> None:
        states = {
            "review": StateDef(
                worker=WorkerDef(
                    kind="claude-code",
                    prompt="prompts/default.md",
                    result_format={
                        "outcome": EnumFieldDef(values=["approve"], description="Decision"),
                        "reason": StringFieldDef(description="Explanation", required_when=["reject"]),
                    },
                ),
                on={},
            ),
        }
        config = _make_config(states=states, initial="review")
        result = build_result_format(config, "default", "review")
        assert result["reason"] == {
            "type": "string",
            "description": "Explanation",
            "required_when": ["reject"],
        }

    def test_list_field(self) -> None:
        states = {
            "scoping": StateDef(
                worker=WorkerDef(
                    kind="claude-code",
                    prompt="prompts/default.md",
                    result_format={
                        "outcome": EnumFieldDef(values=["decompose"], description="Decision"),
                        "sub_issues": ListFieldDef(
                            description="Sub-issues", items="$issue", required_when=["decompose"]
                        ),
                    },
                ),
                on={},
            ),
        }
        config = _make_config(states=states, initial="scoping")
        result = build_result_format(config, "default", "scoping")
        assert result["sub_issues"] == {
            "type": "list",
            "description": "Sub-issues",
            "items": "$issue",
            "required_when": ["decompose"],
        }


class TestTryDispatch:
    def test_dispatch_no_limit(self) -> None:
        config = _make_config()
        state = State(issues={"A": _make_issue(state="todo")}, worker_queues={})
        effects: list[Effect] = []
        try_dispatch(config, state, "A", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "A"
        assert effects[0].state == "todo"
        assert state.issues["A"].worker_active is True

    def test_dispatch_under_limit(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply"),
            },
            worker_queues={},
        )
        effects: list[Effect] = []
        try_dispatch(config, state, "A", effects)
        assert len(effects) == 1
        assert state.issues["A"].worker_active is True

    def test_dispatch_at_limit_queues(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply", worker_active=True),
                "B": _make_issue(state="apply"),
            },
            worker_queues={},
        )
        effects: list[Effect] = []
        try_dispatch(config, state, "B", effects)
        assert len(effects) == 0
        assert state.issues["B"].worker_active is False
        assert state.worker_queues["default:apply"] == ["B"]

    def test_blocked_issue_not_dispatched(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="todo"),
                "B": _make_issue(state="implementing", decomposed_from="A"),
            },
            worker_queues={},
        )
        effects: list[Effect] = []
        try_dispatch(config, state, "A", effects)
        assert len(effects) == 0
        assert state.issues["A"].worker_active is False

    def test_no_worker_not_dispatched(self) -> None:
        config = _make_config()
        state = State(issues={"A": _make_issue(state="done")}, worker_queues={})
        effects: list[Effect] = []
        try_dispatch(config, state, "A", effects)
        assert len(effects) == 0


class TestBackfillQueue:
    def test_backfill_pops_next(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply"),
                "B": _make_issue(state="apply"),
            },
            worker_queues={"default:apply": ["A", "B"]},
        )
        effects: list[Effect] = []
        backfill_queue(config, state, "default:apply", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "A"
        assert state.issues["A"].worker_active is True
        assert state.worker_queues["default:apply"] == ["B"]

    def test_backfill_skips_blocked_decomposition(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply"),
                "B": _make_issue(state="apply"),
                "C": _make_issue(state="implementing", decomposed_from="A"),
            },
            worker_queues={"default:apply": ["A", "B"]},
        )
        effects: list[Effect] = []
        backfill_queue(config, state, "default:apply", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "B"
        assert state.worker_queues["default:apply"] == ["A"]

    def test_backfill_skips_blocked_dependency(self) -> None:
        config = _make_config()
        state = State(
            issues={
                "A": _make_issue(state="apply", depends_on=["C"]),
                "B": _make_issue(state="apply"),
                "C": _make_issue(state="implementing"),
            },
            worker_queues={"default:apply": ["A", "B"]},
        )
        effects: list[Effect] = []
        backfill_queue(config, state, "default:apply", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].issue_id == "B"
        assert state.worker_queues["default:apply"] == ["A"]


class TestRemoveFromQueue:
    def test_remove_existing(self) -> None:
        state = State(issues={}, worker_queues={"default:apply": ["A", "B", "C"]})
        remove_from_queue(state, "default:apply", "B")
        assert state.worker_queues["default:apply"] == ["A", "C"]

    def test_remove_nonexistent_no_error(self) -> None:
        state = State(issues={}, worker_queues={"default:apply": ["A"]})
        remove_from_queue(state, "default:apply", "Z")
        assert state.worker_queues["default:apply"] == ["A"]

    def test_remove_from_missing_queue_no_error(self) -> None:
        state = State(issues={}, worker_queues={})
        remove_from_queue(state, "default:apply", "A")  # should not raise


@pytest.fixture
def simple_config() -> StateMachineConfig:
    return _make_config()


class TestProgressEnabled:
    def test_dispatch_effect_carries_progress_enabled(self) -> None:
        """When worker has progress: true, DispatchWorkerEffect.progress_enabled is True."""
        config = parse_config("""
initial: doing
states:
  doing:
    worker:
      kind: claude-code
      prompt: prompts/doing.md
      progress: true
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Done"
    on:
      done: done
""")
        state = State(issues={}, worker_queues={})
        issue = Issue(
            type="default",
            fields={"title": "Test"},
            state="doing",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
        )
        state.issues["i1"] = issue
        effects: list[Effect] = []
        try_dispatch(config, state, "i1", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].progress_enabled is True

    def test_dispatch_effect_progress_disabled_by_default(self, simple_config: StateMachineConfig) -> None:
        """Without progress: true, progress_enabled is False."""
        state = State(issues={}, worker_queues={})
        issue = Issue(
            type="default",
            fields={"title": "Test"},
            state="todo",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
        )
        state.issues["i1"] = issue
        effects: list[Effect] = []
        try_dispatch(simple_config, state, "i1", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].progress_enabled is False


class TestBuildRunContext:
    def test_file_map(self, tmp_path: _Path) -> None:
        run_dir = tmp_path / ".orca-state" / "runs" / "my-branch" / "prd"
        run_dir.mkdir(parents=True)
        (run_dir / "orca.log.jsonl").touch()
        (run_dir / "state.json").touch()
        sessions_dir = tmp_path / ".orca-state" / "sessions"
        sessions_dir.mkdir(parents=True)

        issue = Issue(
            type="default",
            fields={"title": "test"},
            state="work",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
            visit_counts={"work": 1},
        )
        state = State(issues={"i1": issue}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=[],
            branch="my-branch",
            workflow="prd",
        )

        assert ctx["run_dir"] == str(run_dir)
        assert ctx["repo_root"] == str(tmp_path)
        assert ctx["log"] == str(run_dir / "orca.log.jsonl")
        assert ctx["state"] == str(run_dir / "state.json")
        assert ctx["sessions_dir"] == str(sessions_dir)
        assert ctx["branch"] == "my-branch"
        assert ctx["workflow"] == "prd"

    def test_sessions_list(self, tmp_path: _Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        sessions = [
            {
                "state": "generate_prd",
                "log_path": "/logs/generate_prd-20260402.log",
                "started_at": "2026-04-02T06:00:00+00:00",
                "completed_at": "2026-04-02T06:06:14+00:00",
            },
            {
                "state": "territory_map",
                "log_path": "/logs/territory_map-20260402.log",
                "started_at": "2026-04-02T06:06:14+00:00",
                "completed_at": "2026-04-02T06:08:06+00:00",
            },
        ]

        state = State(issues={}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=sessions,
            branch="b",
            workflow="w",
        )

        assert len(ctx["sessions"]) == 2
        assert ctx["sessions"][0]["state"] == "generate_prd"
        assert ctx["sessions"][0]["log"] == "/logs/generate_prd-20260402.log"
        assert ctx["sessions"][0]["duration"] == "6m 14s"
        assert ctx["sessions"][1]["state"] == "territory_map"
        assert ctx["sessions"][1]["duration"] == "1m 52s"

    def test_summary_from_event_log(self, tmp_path: _Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        issue = Issue(
            type="default",
            fields={"title": "test"},
            state="recon_prd",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[
                EventLogEntry(timestamp="t0", type="created", data={"state": "generate_prd"}),
                EventLogEntry(timestamp="t1", type="worker_dispatched", data={"state": "generate_prd"}),
                EventLogEntry(timestamp="t2", type="worker_result", data={"outcome": "complete"}),
                EventLogEntry(timestamp="t3", type="transitioned", data={"from": "generate_prd", "to": "recon_prd"}),
                EventLogEntry(timestamp="t4", type="worker_dispatched", data={"state": "recon_prd"}),
                EventLogEntry(timestamp="t5", type="worker_failed", data={"state": "recon_prd", "error": "MCP down"}),
            ],
            visit_counts={"generate_prd": 1, "recon_prd": 1},
        )
        state = State(issues={"i1": issue}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=[
                {
                    "state": "generate_prd",
                    "started_at": "2026-04-02T06:00:00+00:00",
                    "completed_at": "2026-04-02T06:10:00+00:00",
                },
            ],
            branch="b",
            workflow="w",
        )

        summary = ctx["summary"]
        assert "generate_prd" in summary["states_visited"]
        assert "recon_prd" in summary["states_visited"]
        assert summary["current_state"] == "recon_prd"
        assert summary["outcomes"]["generate_prd"] == "complete"
        assert "recon_prd" in summary["failures"]
        assert "MCP down" in summary["failures"]["recon_prd"]

    def test_formats_present(self, tmp_path: _Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        state = State(issues={}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=[],
            branch="b",
            workflow="w",
        )

        assert "log" in ctx["formats"]
        assert "state" in ctx["formats"]
        assert "sessions" in ctx["formats"]

    def test_run_context_has_no_removed_eval_key(self, tmp_path: _Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        state = State(issues={}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=[],
            branch="b",
            workflow="w",
        )

        assert "eval_name" not in ctx
