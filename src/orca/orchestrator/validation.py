from __future__ import annotations

from typing import Any


def validate_result(result: dict[str, Any], result_format: dict[str, Any]) -> str | None:
    """Validate a worker result against result_format. Returns error message or None."""
    if not isinstance(result, dict):
        return "Result must be a dict"

    outcome = result.get("outcome")
    if outcome is None:
        return "Result missing required 'outcome' field"

    outcome_def = result_format.get("outcome", {})
    valid_values = outcome_def.get("values", [])
    if outcome not in valid_values:
        return f"Invalid outcome '{outcome}', expected one of {valid_values}"

    for field_name, field_def in result_format.items():
        if field_name == "outcome":
            continue
        if not isinstance(field_def, dict):
            continue
        required_when = field_def.get("required_when", [])
        if outcome in required_when:
            value = result.get(field_name)
            if field_def.get("type") == "list":
                if not value:
                    return f"Field '{field_name}' must be a non-empty list when outcome is '{outcome}'"
            elif not value:
                return f"Field '{field_name}' is required when outcome is '{outcome}'"

    return None
