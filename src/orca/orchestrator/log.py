from __future__ import annotations

import json
import logging
import os
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
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(log_path: Path, level: int = logging.DEBUG) -> None:
    """Configure the 'orca' logger to write JSONL to a file.

    Idempotent: repeated calls with the same path keep the existing handler,
    and calls with a new path remove + close the old file handler first —
    otherwise every run would stack another FileHandler on the shared
    'orca' logger (duplicated records, leaked file descriptors).
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    target = os.path.abspath(log_path)
    orca_logger = logging.getLogger("orca")

    has_target = False
    for existing in list(orca_logger.handlers):
        if not isinstance(existing, logging.FileHandler):
            continue
        if existing.baseFilename == target:
            has_target = True
            continue
        orca_logger.removeHandler(existing)
        existing.close()

    orca_logger.setLevel(level)
    orca_logger.propagate = False
    if has_target:
        return

    handler = logging.FileHandler(log_path)
    handler.setFormatter(JSONFormatter())
    orca_logger.addHandler(handler)
