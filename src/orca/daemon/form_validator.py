"""Form submission validator.

Pure function: takes a form schema (as emitted by a worker's `waiting`
outcome) and a values dict (as POSTed from the browser), returns a mapping
of field-name -> short error code. An empty dict means the submission is
valid against the schema.

Error codes:
- "required"      — a required field is missing or empty.
- "type"          — value has the wrong type for the declared field type.
- "min" / "max"   — number is outside the allowed range.
- "pattern"       — string doesn't match the declared regex.
- "unknown_field" — the values dict contains a key not declared in the schema.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _iter_fields(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for step in schema.get("steps", []):
        for block in step.get("blocks", []):
            if block.get("kind") == "field":
                yield block


def _iter_value_carrying_blocks(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield blocks whose `name` appears in the submitted `values` dict
    even though they aren't `field` blocks — currently the `changeset`
    block, whose web component writes its comments array under
    `values[block.name]`. The validator must treat these as known keys
    (no per-field validation, just acceptance) or every submission with
    a changeset would return 422 `unknown_field`.
    """
    for step in schema.get("steps", []):
        for block in step.get("blocks", []):
            if block.get("kind") == "changeset" and "name" in block:
                yield block


def validate_submission(schema: dict[str, Any], values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    known: set[str] = set()

    for blk in _iter_value_carrying_blocks(schema):
        known.add(blk["name"])

    for fld in _iter_fields(schema):
        name = fld["name"]
        known.add(name)
        value = values.get(name)
        ftype = fld["type"]

        is_empty = value is None or value == "" or (ftype == "checkbox" and value is False)

        if fld.get("required") and is_empty:
            errors[name] = "required"
            continue
        if is_empty:
            continue

        if ftype in ("text", "password", "textarea", "date"):
            if not isinstance(value, str):
                errors[name] = "type"
                continue
            pattern = fld.get("pattern")
            if pattern and not re.search(pattern, value):
                errors[name] = "pattern"
        elif ftype == "email":
            if not isinstance(value, str) or not _EMAIL_RE.match(value):
                errors[name] = "type"
        elif ftype == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                errors[name] = "type"
                continue
            if "min" in fld and value < fld["min"]:
                errors[name] = "min"
            elif "max" in fld and value > fld["max"]:
                errors[name] = "max"
        elif ftype == "checkbox":
            if not isinstance(value, bool):
                errors[name] = "type"
        elif ftype == "select":
            valid = {o.get("value") for o in fld.get("options", [])}
            if value not in valid:
                errors[name] = "type"

    for k in values:
        if k not in known:
            errors[k] = "unknown_field"

    return errors
