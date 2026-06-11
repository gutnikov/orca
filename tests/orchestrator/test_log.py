from __future__ import annotations

import json
import logging
from pathlib import Path

from orca.orchestrator.log import JSONFormatter, setup_logging


class TestJSONFormatter:
    def setup_method(self) -> None:
        self.formatter = JSONFormatter()

    def test_formats_basic_record(self) -> None:
        record = logging.LogRecord(
            name="orca.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        output = self.formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "orca.test"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed

    def test_includes_extra_fields(self) -> None:
        record = logging.LogRecord(
            name="orca.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="dispatch",
            args=(),
            exc_info=None,
        )
        record.event = "worker_dispatched"
        record.worker_id = "w-123"
        output = self.formatter.format(record)
        parsed = json.loads(output)
        assert parsed["event"] == "worker_dispatched"
        assert parsed["worker_id"] == "w-123"

    def test_excludes_standard_log_record_attrs(self) -> None:
        record = logging.LogRecord(
            name="orca.test",
            level=logging.INFO,
            pathname="/some/path.py",
            lineno=42,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = self.formatter.format(record)
        parsed = json.loads(output)
        assert "pathname" not in parsed
        assert "lineno" not in parsed
        assert "args" not in parsed
        assert "msg" not in parsed

    def test_output_is_single_line(self) -> None:
        record = logging.LogRecord(
            name="orca.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="line1\nline2\nline3",
            args=(),
            exc_info=None,
        )
        output = self.formatter.format(record)
        assert "\n" not in output
        parsed = json.loads(output)
        assert parsed["message"] == "line1\nline2\nline3"


class TestSetupLogging:
    def teardown_method(self) -> None:
        logger = logging.getLogger("orca")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_creates_log_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "logs" / "orca.jsonl"
        setup_logging(log_file)
        logger = logging.getLogger("orca")
        logger.info("test message")

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["message"] == "test message"
        assert parsed["level"] == "INFO"

    def test_does_not_propagate(self, tmp_path: Path) -> None:
        log_file = tmp_path / "orca.jsonl"
        setup_logging(log_file)
        logger = logging.getLogger("orca")
        assert logger.propagate is False

    def test_repeated_setup_same_path_does_not_stack_handlers(self, tmp_path: Path) -> None:
        log_file = tmp_path / "orca.jsonl"
        setup_logging(log_file)
        setup_logging(log_file)
        setup_logging(log_file)

        logger = logging.getLogger("orca")
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1

        logger.info("logged once")
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1

    def test_setup_with_new_path_replaces_old_handler(self, tmp_path: Path) -> None:
        first = tmp_path / "run1" / "orca.jsonl"
        second = tmp_path / "run2" / "orca.jsonl"
        setup_logging(first)
        setup_logging(second)

        logger = logging.getLogger("orca")
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1

        logger.info("only to second")
        assert "only to second" in second.read_text()
        assert "only to second" not in first.read_text()
