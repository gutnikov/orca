from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

UsageTokens = dict[str, int]
UsageSnapshot = dict[str, Any]

_ORCA_USAGE_MARKER_PREFIX = "ORCA_USAGE_SESSION"
_COLLECT_WINDOW = timedelta(minutes=5)


def usage_marker(session_id: str) -> str:
    return f"{_ORCA_USAGE_MARKER_PREFIX}:{session_id}"


def collect_usage(entry: Mapping[str, Any]) -> UsageSnapshot | None:
    kind = entry.get("worker_kind")
    worktree_path = entry.get("worktree_path")
    marker = entry.get("usage_marker")
    started_at = _parse_datetime(entry.get("started_at"))
    if not isinstance(kind, str) or not isinstance(worktree_path, str) or not isinstance(marker, str):
        return None
    if started_at is None:
        return None

    if kind == "claude-code":
        return _collect_claude(Path(worktree_path), marker, started_at)
    if kind == "codex":
        return _collect_codex(Path(worktree_path), marker, started_at)
    if kind == "opencode":
        return _collect_opencode(Path(worktree_path), marker, started_at)
    return None


def _collect_claude(workdir: Path, marker: str, started_at: datetime) -> UsageSnapshot | None:
    project_dir = _home() / ".claude" / "projects" / _claude_project_name(workdir)
    if not project_dir.exists():
        return None

    for path in _recent_files(project_dir.rglob("*.jsonl"), started_at):
        result = _parse_claude_file(path, marker)
        if result is not None:
            return result
    return None


def _parse_claude_file(path: Path, marker: str) -> UsageSnapshot | None:
    marker_ts: datetime | None = None
    external_session_id: str | None = None
    model: str | None = None
    usage_by_request: dict[str, UsageTokens] = {}

    for raw, obj in _iter_jsonl(path):
        if marker_ts is None and marker in raw:
            marker_ts = _parse_datetime(obj.get("timestamp")) or datetime.fromtimestamp(path.stat().st_mtime, UTC)
            session_id = obj.get("sessionId")
            external_session_id = session_id if isinstance(session_id, str) else None
            continue

        if marker_ts is None:
            continue
        timestamp = _parse_datetime(obj.get("timestamp"))
        if timestamp is not None and timestamp < marker_ts:
            continue
        if external_session_id is not None and obj.get("sessionId") != external_session_id:
            continue
        if obj.get("type") != "assistant":
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        raw_model = message.get("model")
        if isinstance(raw_model, str):
            model = raw_model
        request_id = obj.get("requestId")
        if not isinstance(request_id, str):
            message_id = message.get("id")
            timestamp = obj.get("timestamp")
            request_id = f"{message_id}:{timestamp}" if isinstance(message_id, str) else raw
        usage_by_request[request_id] = {
            "input": _int(usage.get("input_tokens")),
            "output": _int(usage.get("output_tokens")),
            "reasoning": 0,
            "cache_read": _int(usage.get("cache_read_input_tokens")),
            "cache_write": _int(usage.get("cache_creation_input_tokens")),
        }

    if marker_ts is None or not usage_by_request:
        return None
    tokens = _sum_tokens(usage_by_request.values())
    return _snapshot(
        source="claude-code",
        tokens=tokens,
        model=model,
        external_session_id=external_session_id,
        cost_usd=_estimate_cost(model, tokens),
    )


def _collect_codex(workdir: Path, marker: str, started_at: datetime) -> UsageSnapshot | None:
    sessions_dir = _home() / ".codex" / "sessions"
    if not sessions_dir.exists():
        return None

    for path in _recent_files(sessions_dir.rglob("*.jsonl"), started_at):
        result = _parse_codex_file(path, marker, workdir)
        if result is not None:
            return result
    return None


def _parse_codex_file(path: Path, marker: str, workdir: Path) -> UsageSnapshot | None:
    marker_ts: datetime | None = None
    external_session_id: str | None = None
    model: str | None = None
    cwd_matches = False
    before_total: UsageTokens | None = None
    after_total: UsageTokens | None = None

    for raw, obj in _iter_jsonl(path):
        timestamp = _parse_datetime(obj.get("timestamp"))
        obj_type = obj.get("type")
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue

        if obj_type == "session_meta":
            session_id = payload.get("id")
            external_session_id = session_id if isinstance(session_id, str) else external_session_id
            cwd = payload.get("cwd")
            cwd_matches = isinstance(cwd, str) and _same_path(cwd, workdir)
        elif obj_type == "turn_context":
            raw_model = payload.get("model")
            if isinstance(raw_model, str):
                model = raw_model

        if marker_ts is None and marker in raw:
            marker_ts = timestamp or datetime.fromtimestamp(path.stat().st_mtime, UTC)
            continue

        if obj_type != "event_msg" or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if not isinstance(info, dict):
            continue
        total = _codex_tokens(info.get("total_token_usage"))
        if total is None:
            continue
        if marker_ts is None:
            before_total = total
        elif timestamp is None or timestamp >= marker_ts:
            after_total = total

    if marker_ts is None or after_total is None:
        return None
    if not cwd_matches and workdir.exists():
        return None
    tokens = _subtract_tokens(after_total, before_total)
    return _snapshot(
        source="codex",
        tokens=tokens,
        model=model,
        external_session_id=external_session_id,
        cost_usd=_estimate_cost(model, tokens),
    )


def _collect_opencode(workdir: Path, marker: str, started_at: datetime) -> UsageSnapshot | None:
    db_path = _opencode_db_path()
    if not db_path.exists():
        return None

    start_ms = int((started_at - _COLLECT_WINDOW).timestamp() * 1000)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.25)
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            select s.*
            from session s
            where exists (
                select 1 from message m
                where m.session_id = s.id and m.data like ?
            )
            or exists (
                select 1 from part p
                where p.session_id = s.id and p.data like ?
            )
            order by s.time_created desc
            limit 1
            """,
            (f"%{marker}%", f"%{marker}%"),
        ).fetchone()
        if row is None:
            row = conn.execute(
                """
                select *
                from session
                where directory = ? and time_created >= ?
                order by time_created asc
                limit 1
                """,
                (str(workdir), start_ms),
            ).fetchone()
        if row is None:
            return None
        tokens = {
            "input": _int(row["tokens_input"]),
            "output": _int(row["tokens_output"]),
            "reasoning": _int(row["tokens_reasoning"]),
            "cache_read": _int(row["tokens_cache_read"]),
            "cache_write": _int(row["tokens_cache_write"]),
        }
        return _snapshot(
            source="opencode",
            tokens=tokens,
            model=row["model"] if isinstance(row["model"], str) else None,
            external_session_id=row["id"] if isinstance(row["id"], str) else None,
            cost_usd=float(row["cost"]),
            cost_kind="exact",
        )
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _snapshot(
    *,
    source: str,
    tokens: UsageTokens,
    model: str | None,
    external_session_id: str | None,
    cost_usd: float | None,
    cost_kind: str | None = None,
) -> UsageSnapshot:
    result: UsageSnapshot = {
        "source": source,
        "tokens": tokens,
        "total_tokens": sum(tokens.values()),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if model:
        result["model"] = model
    if external_session_id:
        result["external_session_id"] = external_session_id
    if cost_usd is not None:
        result["cost_usd"] = cost_usd
        result["cost_kind"] = cost_kind or "estimated"
    return result


def _estimate_cost(model: str | None, tokens: UsageTokens) -> float | None:
    if not model:
        return None
    price = _price_for_model(model)
    if price is None:
        return None
    input_tokens = max(tokens["input"] - tokens["cache_read"] - tokens["cache_write"], 0)
    output_tokens = tokens["output"] + tokens["reasoning"]
    total = (
        input_tokens * price["input"]
        + output_tokens * price["output"]
        + tokens["cache_read"] * price.get("cache_read", price["input"])
        + tokens["cache_write"] * price.get("cache_write", price["input"])
    )
    return total / 1_000_000


def _price_for_model(model: str) -> dict[str, float] | None:
    table = _price_table()
    candidates = [model]
    if "/" in model:
        candidates.append(model.rsplit("/", 1)[1])
    for candidate in candidates:
        value = table.get(candidate)
        if value is not None:
            return value
    return None


def _price_table() -> dict[str, dict[str, float]]:
    raw = os.environ.get("ORCA_USAGE_PRICES_JSON")
    if raw:
        parsed = _parse_price_table(raw)
        if parsed:
            return parsed

    file_name = os.environ.get("ORCA_USAGE_PRICES_FILE")
    if file_name:
        try:
            parsed = _parse_price_table(Path(file_name).expanduser().read_text())
        except OSError:
            parsed = {}
        if parsed:
            return parsed

    return {}


def _parse_price_table(raw: str) -> dict[str, dict[str, float]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, float]] = {}
    for model, prices in data.items():
        if not isinstance(model, str) or not isinstance(prices, dict):
            continue
        input_price = _float(prices.get("input"))
        output_price = _float(prices.get("output"))
        if input_price is None or output_price is None:
            continue
        item: dict[str, float] = {"input": input_price, "output": output_price}
        cache_read = _float(prices.get("cache_read"))
        cache_write = _float(prices.get("cache_write"))
        if cache_read is not None:
            item["cache_read"] = cache_read
        if cache_write is not None:
            item["cache_write"] = cache_write
        result[model] = item
    return result


def _codex_tokens(value: Any) -> UsageTokens | None:
    if not isinstance(value, dict):
        return None
    return {
        "input": _int(value.get("input_tokens")),
        "output": _int(value.get("output_tokens")),
        "reasoning": _int(value.get("reasoning_output_tokens")),
        "cache_read": _int(value.get("cached_input_tokens")),
        "cache_write": 0,
    }


def _sum_tokens(values: Iterable[UsageTokens]) -> UsageTokens:
    total = _empty_tokens()
    for value in values:
        for key in total:
            total[key] += value.get(key, 0)
    return total


def _subtract_tokens(value: UsageTokens, previous: UsageTokens | None) -> UsageTokens:
    if previous is None:
        return dict(value)
    return {key: max(value.get(key, 0) - previous.get(key, 0), 0) for key in _empty_tokens()}


def _empty_tokens() -> UsageTokens:
    return {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}


def _iter_jsonl(path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    try:
        with path.open() as handle:
            for raw in handle:
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield raw, obj
    except OSError:
        return


def _recent_files(paths: Iterable[Path], started_at: datetime) -> list[Path]:
    threshold = (started_at - _COLLECT_WINDOW).timestamp()
    candidates: list[Path] = []
    for path in paths:
        try:
            if path.stat().st_mtime >= threshold:
                candidates.append(path)
        except OSError:
            continue
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _home() -> Path:
    return Path(os.environ.get("HOME", "~")).expanduser()


def _opencode_db_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home).expanduser() / "opencode" / "opencode.db"
    return _home() / ".local" / "share" / "opencode" / "opencode.db"


def _claude_project_name(workdir: Path) -> str:
    return str(workdir).replace("/", "-")


def _same_path(left: str, right: Path) -> bool:
    try:
        return Path(left).resolve() == right.resolve()
    except OSError:
        return left == str(right)
