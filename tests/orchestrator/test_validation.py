from __future__ import annotations

from orca.orchestrator.validation import validate_result

RESULT_FORMAT: dict[str, dict[str, object]] = {
    "outcome": {
        "type": "enum",
        "values": ["done", "split"],
        "description": "Outcome",
    },
    "summary": {
        "type": "string",
        "description": "Summary",
        "required_when": ["done"],
    },
    "sub_issues": {
        "type": "list",
        "items": "$issue",
        "description": "Sub-tasks",
        "required_when": ["split"],
    },
}


class TestValidateResult:
    def test_valid_done_result(self) -> None:
        result = {"outcome": "done", "summary": "All good"}
        assert validate_result(result, RESULT_FORMAT) is None

    def test_valid_split_result(self) -> None:
        result = {
            "outcome": "split",
            "sub_issues": [{"key": "a", "fields": {"title": "A"}}],
        }
        assert validate_result(result, RESULT_FORMAT) is None

    def test_missing_outcome(self) -> None:
        result = {"summary": "oops"}
        error = validate_result(result, RESULT_FORMAT)
        assert error is not None
        assert "outcome" in error

    def test_invalid_outcome_value(self) -> None:
        result = {"outcome": "unknown"}
        error = validate_result(result, RESULT_FORMAT)
        assert error is not None
        assert "unknown" in error

    def test_missing_required_field(self) -> None:
        result = {"outcome": "done"}
        error = validate_result(result, RESULT_FORMAT)
        assert error is not None
        assert "summary" in error

    def test_empty_required_field(self) -> None:
        result = {"outcome": "done", "summary": ""}
        error = validate_result(result, RESULT_FORMAT)
        assert error is not None
        assert "summary" in error

    def test_empty_sub_issues_for_split(self) -> None:
        result = {"outcome": "split", "sub_issues": []}
        error = validate_result(result, RESULT_FORMAT)
        assert error is not None
        assert "sub_issues" in error

    def test_extra_fields_ignored(self) -> None:
        result = {"outcome": "done", "summary": "ok", "extra": "field"}
        assert validate_result(result, RESULT_FORMAT) is None

    def test_not_a_dict(self) -> None:
        error = validate_result("not a dict", RESULT_FORMAT)  # type: ignore[arg-type]
        assert error is not None

    def test_required_when_not_matching(self) -> None:
        result = {
            "outcome": "split",
            "sub_issues": [{"key": "a", "fields": {"title": "A"}}],
        }
        assert validate_result(result, RESULT_FORMAT) is None
