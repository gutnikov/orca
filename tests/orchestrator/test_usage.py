from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from orca.orchestrator.usage import collect_usage, usage_marker


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def test_collect_claude_usage_from_project_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    marker = usage_marker("sess-1")

    project_dir = home / ".claude" / "projects" / str(workdir).replace("/", "-")
    _jsonl(
        project_dir / "abc.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "user",
                "sessionId": "claude-session",
                "message": {"role": "user", "content": marker},
            },
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "type": "assistant",
                "sessionId": "claude-session",
                "requestId": "req-1",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 4,
                        "cache_read_input_tokens": 2,
                        "output_tokens": 8,
                    },
                },
            },
            {
                "timestamp": "2026-01-01T00:00:02Z",
                "type": "assistant",
                "sessionId": "claude-session",
                "requestId": "req-1",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 4,
                        "cache_read_input_tokens": 2,
                        "output_tokens": 8,
                    },
                },
            },
        ],
    )

    usage = collect_usage(
        {
            "worker_kind": "claude-code",
            "worktree_path": str(workdir),
            "usage_marker": marker,
            "started_at": "2026-01-01T00:00:00Z",
        }
    )

    assert usage is not None
    assert usage["source"] == "claude-code"
    assert usage["external_session_id"] == "claude-session"
    assert usage["model"] == "claude-test"
    assert usage["tokens"] == {"input": 10, "output": 8, "reasoning": 0, "cache_read": 2, "cache_write": 4}


def test_collect_claude_usage_without_marker_uses_normalized_project_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "repo.with_underscore"
    workdir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(
        "ORCA_USAGE_PRICES_JSON",
        json.dumps({"claude-test": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75}}),
    )

    project_name = "".join(ch if ch.isalnum() else "-" for ch in str(workdir))
    project_dir = home / ".claude" / "projects" / project_name
    _jsonl(
        project_dir / "abc.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "user",
                "sessionId": "claude-session",
                "message": {"role": "user", "content": "worker prompt"},
            },
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "type": "assistant",
                "sessionId": "claude-session",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 4,
                        "cache_read_input_tokens": 2,
                        "output_tokens": 8,
                    },
                },
            },
            {
                "timestamp": "2026-01-01T00:00:02Z",
                "type": "assistant",
                "sessionId": "claude-session",
                "message": {
                    "id": "msg-1",
                    "model": "claude-test",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 4,
                        "cache_read_input_tokens": 2,
                        "output_tokens": 8,
                    },
                },
            },
        ],
    )
    _jsonl(
        project_dir / "future.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:10:00Z",
                "type": "assistant",
                "sessionId": "future-session",
                "message": {
                    "id": "msg-future",
                    "model": "claude-test",
                    "usage": {"input_tokens": 100, "output_tokens": 100},
                },
            }
        ],
    )

    usage = collect_usage(
        {
            "worker_kind": "claude-code",
            "worktree_path": str(workdir),
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:05Z",
        }
    )

    assert usage is not None
    assert usage["source"] == "claude-code"
    assert usage["external_session_id"] == "claude-session"
    assert usage["tokens"] == {"input": 10, "output": 8, "reasoning": 0, "cache_read": 2, "cache_write": 4}
    assert usage["cost_kind"] == "estimated"
    assert usage["cost_usd"] == pytest.approx(0.0001656)


def test_collect_claude_usage_uses_model_hint_and_builtin_price(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ORCA_USAGE_PRICES_JSON", raising=False)
    monkeypatch.delenv("ORCA_USAGE_PRICES_FILE", raising=False)
    marker = usage_marker("sess-1")

    project_dir = home / ".claude" / "projects" / str(workdir).replace("/", "-")
    _jsonl(
        project_dir / "abc.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "user",
                "sessionId": "claude-session",
                "message": {"role": "user", "content": marker},
            },
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "type": "assistant",
                "sessionId": "claude-session",
                "message": {
                    "id": "msg-1",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 4,
                        "cache_read_input_tokens": 2,
                        "output_tokens": 8,
                    },
                },
            },
        ],
    )

    usage = collect_usage(
        {
            "worker_kind": "claude-code",
            "worktree_path": str(workdir),
            "usage_marker": marker,
            "started_at": "2026-01-01T00:00:00Z",
            "model": "us.anthropic.claude-opus-4-6-v1",
        }
    )

    assert usage is not None
    assert usage["model"] == "us.anthropic.claude-opus-4-6-v1"
    assert usage["cost_kind"] == "estimated"
    assert usage["cost_usd"] == pytest.approx(0.000276)


def test_collect_claude_usage_prices_dated_bedrock_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ORCA_USAGE_PRICES_JSON", raising=False)
    monkeypatch.delenv("ORCA_USAGE_PRICES_FILE", raising=False)
    marker = usage_marker("sess-1")

    project_dir = home / ".claude" / "projects" / str(workdir).replace("/", "-")
    _jsonl(
        project_dir / "abc.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "user",
                "sessionId": "claude-session",
                "message": {"role": "user", "content": marker},
            },
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "type": "assistant",
                "sessionId": "claude-session",
                "message": {
                    "id": "msg-1",
                    "model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 4,
                        "cache_read_input_tokens": 2,
                        "output_tokens": 8,
                    },
                },
            },
        ],
    )

    usage = collect_usage(
        {
            "worker_kind": "claude-code",
            "worktree_path": str(workdir),
            "usage_marker": marker,
            "started_at": "2026-01-01T00:00:00Z",
            "model": "haiku",
        }
    )

    assert usage is not None
    assert usage["model"] == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert usage["cost_kind"] == "estimated"
    assert usage["cost_usd"] == pytest.approx(0.0000552)


def test_collect_codex_usage_uses_token_count_delta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(
        "ORCA_USAGE_PRICES_JSON",
        json.dumps({"gpt-test": {"input": 1.0, "output": 10.0, "cache_read": 0.1}}),
    )
    marker = usage_marker("sess-2")

    _jsonl(
        home / ".codex" / "sessions" / "2026" / "01" / "01" / "rollout.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": "codex-session", "cwd": str(workdir)},
            },
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "turn_context",
                "payload": {"model": "gpt-test"},
            },
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 10,
                            "reasoning_output_tokens": 2,
                        }
                    },
                },
            },
            {"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg", "payload": {"message": marker}},
            {
                "timestamp": "2026-01-01T00:00:03Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 160,
                            "cached_input_tokens": 30,
                            "output_tokens": 18,
                            "reasoning_output_tokens": 5,
                        }
                    },
                },
            },
        ],
    )

    usage = collect_usage(
        {
            "worker_kind": "codex",
            "worktree_path": str(workdir),
            "usage_marker": marker,
            "started_at": "2026-01-01T00:00:00Z",
        }
    )

    assert usage is not None
    assert usage["source"] == "codex"
    assert usage["external_session_id"] == "codex-session"
    assert usage["tokens"] == {"input": 60, "output": 8, "reasoning": 3, "cache_read": 10, "cache_write": 0}
    assert usage["cost_kind"] == "estimated"
    assert usage["cost_usd"] == pytest.approx(0.000161)


def test_collect_opencode_usage_from_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_home = tmp_path / "data"
    workdir = tmp_path / "repo"
    workdir.mkdir()
    db_path = data_home / "opencode" / "opencode.db"
    db_path.parent.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    marker = usage_marker("sess-3")

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        create table session (
          id text primary key,
          directory text not null,
          time_created integer not null,
          model text,
          cost real,
          tokens_input integer,
          tokens_output integer,
          tokens_reasoning integer,
          tokens_cache_read integer,
          tokens_cache_write integer
        );
        create table message (id text primary key, session_id text, data text);
        create table part (id text primary key, session_id text, data text);
        """
    )
    conn.execute(
        "insert into session values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("opencode-session", str(workdir), 1_767_225_600_000, "anthropic/claude-test", 0.42, 10, 20, 3, 4, 5),
    )
    conn.execute(
        "insert into message values (?, ?, ?)",
        ("msg-1", "opencode-session", json.dumps({"role": "user", "content": marker})),
    )
    conn.commit()
    conn.close()

    usage = collect_usage(
        {
            "worker_kind": "opencode",
            "worktree_path": str(workdir),
            "usage_marker": marker,
            "started_at": "2026-01-01T00:00:00Z",
        }
    )

    assert usage is not None
    assert usage["source"] == "opencode"
    assert usage["external_session_id"] == "opencode-session"
    assert usage["cost_usd"] == 0.42
    assert usage["cost_kind"] == "exact"
    assert usage["tokens"] == {"input": 10, "output": 20, "reasoning": 3, "cache_read": 4, "cache_write": 5}
