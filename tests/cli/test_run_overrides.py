"""Tests for the `orca run --override` flag parser."""

from __future__ import annotations

import pytest

from orca.cli.run_cmd import parse_worker_overrides


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
