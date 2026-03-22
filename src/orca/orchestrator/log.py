from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

_STANDARD_LOG_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS and key not in entry:
                entry[key] = value
        return json.dumps(entry, default=str)


def setup_logging(log_path: Path, level: int = logging.DEBUG) -> None:
    """Configure the 'orca' logger to write JSONL to a file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path)
    handler.setFormatter(JSONFormatter())
    orca_logger = logging.getLogger("orca")
    orca_logger.setLevel(level)
    orca_logger.addHandler(handler)
    orca_logger.propagate = False
