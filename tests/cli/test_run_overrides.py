"""Tests for the `orca run --override` flag parser and payload building."""

from __future__ import annotations

from pathlib import Path

import pytest

from orca.cli.main import build_parser
from orca.cli.run_cmd import build_run_payload, parse_worker_overrides


def test_no_overrides_returns_empty_dict() -> None:
    assert parse_worker_overrides(None) == {}
    assert parse_worker_overrides([]) == {}


def test_single_override_parses_nested() -> None:
    result = parse_worker_overrides(["preflight.kind=codex"])
    assert result == {"preflight": {"kind": "codex"}}


def test_multiple_overrides_merge_under_same_state() -> None:
    result = parse_worker_overrides(
        [
            "preflight.kind=codex",
            "preflight.model=gpt-5.5",
            "preflight.effort=high",
        ]
    )
    assert result == {
        "preflight": {"kind": "codex", "model": "gpt-5.5", "effort": "high"},
    }


def test_overrides_across_multiple_states() -> None:
    result = parse_worker_overrides(["preflight.kind=codex", "implementing.model=claude-opus-4-7"])
    assert result == {
        "preflight": {"kind": "codex"},
        "implementing": {"model": "claude-opus-4-7"},
    }


def test_later_override_wins_for_same_field() -> None:
    result = parse_worker_overrides(["preflight.kind=codex", "preflight.kind=claude-code"])
    assert result == {"preflight": {"kind": "claude-code"}}


def test_missing_equals_raises() -> None:
    with pytest.raises(ValueError, match="<state>.<field>=<value>"):
        parse_worker_overrides(["preflight.kind"])


def test_missing_dot_raises() -> None:
    with pytest.raises(ValueError, match="<state>.<field>"):
        parse_worker_overrides(["preflight=codex"])


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        parse_worker_overrides(["preflight.cooldown=10"])


def test_empty_value_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_worker_overrides(["preflight.kind="])


def test_value_can_contain_equals() -> None:
    """Model names sometimes carry version suffixes that don't contain '=',
    but if someone passes an unusual value the parser shouldn't choke on it."""
    result = parse_worker_overrides(["preflight.model=foo=bar"])
    assert result == {"preflight": {"model": "foo=bar"}}


class TestBuildRunPayload:
    """--max-hops / --max-retries must not clobber the workflow YAML's values.

    The daemon only overrides the workflow config when the keys are present
    and non-None, so the CLI must omit them unless the user passed the flags.
    """

    def _args(self, argv: list[str]) -> object:
        return build_parser().parse_args(["run", "task.md", *argv])

    def test_limits_omitted_when_not_passed(self) -> None:
        payload = build_run_payload(self._args([]), {})
        assert "max_hops" not in payload
        assert "max_retries" not in payload

    def test_limits_included_when_passed(self) -> None:
        payload = build_run_payload(self._args(["--max-hops", "50", "--max-retries", "5"]), {})
        assert payload["max_hops"] == 50
        assert payload["max_retries"] == 5

    def test_base_fields_always_present(self) -> None:
        payload = build_run_payload(self._args(["-w", "develop", "-b", "feat/x"]), {})
        assert payload["task_file"] == str(Path("task.md").resolve())
        assert payload["workflow"] == "develop"
        assert payload["branch"] == "feat/x"
        assert payload["headless"] is False
        assert payload["debug"] is False
        assert "worker_overrides" not in payload

    def test_worker_overrides_included_when_present(self) -> None:
        overrides = {"preflight": {"kind": "codex"}}
        payload = build_run_payload(self._args([]), overrides)
        assert payload["worker_overrides"] == overrides
