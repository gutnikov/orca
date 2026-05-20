from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    ErrorEffect,
    State,
    WorkerResumedEvent,
    WorkerWaitingEvent,
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


SCHEMA = {
    "title": "Test",
    "steps": [{"blocks": [{"kind": "field", "name": "x", "type": "text", "label": "X"}]}],
}


class TestPendingForm:
    def test_set_on_waiting(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerWaitingEvent(issue_id="A", reason="r", timestamp="t1", form=SCHEMA),
            gen,
            _clock(),
        )
        assert state.issues["A"].pending_form == SCHEMA
        assert state.issues["A"].pending_form_submitted_at is None

    def test_no_form_keeps_pending_none(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerWaitingEvent(issue_id="A", reason="r", timestamp="t1"),
            gen,
            _clock(),
        )
        assert state.issues["A"].pending_form is None

    def test_cleared_on_resume(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerWaitingEvent(issue_id="A", reason="r", timestamp="t1", form=SCHEMA),
            gen,
            _clock(),
        )
        state, _ = reduce(
            config,
            state,
            WorkerResumedEvent(issue_id="A", message="m", timestamp="t2"),
            gen,
            _clock(),
        )
        assert state.issues["A"].pending_form is None
        assert state.issues["A"].pending_form_submitted_at is None

    def test_duplicate_field_names_rejected(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()
        state, _ = reduce(
            config,
            state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen,
            _clock(),
        )

        bad_schema = {
            "title": "Bad",
            "steps": [
                {"blocks": [{"kind": "field", "name": "dup", "type": "text", "label": "A"}]},
                {"blocks": [{"kind": "field", "name": "dup", "type": "text", "label": "B"}]},
            ],
        }
        state, effects = reduce(
            config,
            state,
            WorkerWaitingEvent(issue_id="A", reason="r", timestamp="t1", form=bad_schema),
            gen,
            _clock(),
        )
        assert state.issues["A"].pending_form is None
        assert any(isinstance(e, ErrorEffect) and "duplicate" in e.message.lower() for e in effects)

    def test_roundtrip_serialization(self) -> None:
        """Pending-form fields survive Issue.to_dict / from_dict."""
        from orca.engine.types import Issue

        issue = Issue(
            type="issue",
            fields={"title": "T"},
            state="todo",
            worker_active=True,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
            pending_form=SCHEMA,
            pending_form_submitted_at="2026-05-20T14:18:47Z",
        )
        restored = Issue.from_dict(issue.to_dict())
        assert restored.pending_form == SCHEMA
        assert restored.pending_form_submitted_at == "2026-05-20T14:18:47Z"

    def test_legacy_state_loads_without_form_keys(self) -> None:
        """from_dict tolerates state written before the new fields existed."""
        from orca.engine.types import Issue

        legacy = {
            "type": "issue",
            "fields": {"title": "T"},
            "state": "todo",
            "worker_active": False,
            "decomposed_from": None,
            "depends_on": [],
            "event_log": [],
        }
        restored = Issue.from_dict(legacy)
        assert restored.pending_form is None
        assert restored.pending_form_submitted_at is None
