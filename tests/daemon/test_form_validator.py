"""Tests for the pure-function form validator."""

from __future__ import annotations

from typing import Any

from orca.daemon.form_validator import validate_submission

SCHEMA: dict[str, Any] = {
    "title": "Test",
    "steps": [
        {
            "blocks": [
                {"kind": "markdown", "content": "ignore me"},
                {"kind": "field", "name": "name", "type": "text", "label": "Name", "required": True},
                {"kind": "field", "name": "age", "type": "number", "label": "Age", "min": 0, "max": 120},
                {"kind": "field", "name": "email", "type": "email", "label": "Email"},
                {"kind": "field", "name": "notes", "type": "textarea", "label": "Notes", "pattern": r"^[A-Za-z ]+$"},
                {
                    "kind": "field",
                    "name": "color",
                    "type": "select",
                    "label": "Color",
                    "options": [{"value": "red", "label": "Red"}, {"value": "blue", "label": "Blue"}],
                },
                {"kind": "field", "name": "accept", "type": "checkbox", "label": "Accept", "required": True},
            ]
        }
    ],
}


def test_happy_path() -> None:
    assert (
        validate_submission(
            SCHEMA,
            {"name": "Ada", "age": 30, "email": "a@b.c", "notes": "looks good", "color": "red", "accept": True},
        )
        == {}
    )


def test_missing_required_field() -> None:
    errs = validate_submission(SCHEMA, {"age": 5, "accept": True})
    assert errs == {"name": "required"}


def test_missing_required_checkbox() -> None:
    errs = validate_submission(SCHEMA, {"name": "Ada"})
    assert errs == {"accept": "required"}


def test_number_type_mismatch() -> None:
    errs = validate_submission(SCHEMA, {"name": "x", "age": "not-a-number", "accept": True})
    assert errs == {"age": "type"}


def test_number_below_min() -> None:
    errs = validate_submission(SCHEMA, {"name": "x", "age": -5, "accept": True})
    assert errs == {"age": "min"}


def test_number_above_max() -> None:
    errs = validate_submission(SCHEMA, {"name": "x", "age": 200, "accept": True})
    assert errs == {"age": "max"}


def test_email_format() -> None:
    errs = validate_submission(SCHEMA, {"name": "x", "email": "not-email", "accept": True})
    assert errs == {"email": "type"}


def test_pattern_failure() -> None:
    errs = validate_submission(SCHEMA, {"name": "x", "notes": "has 123 digits", "accept": True})
    assert errs == {"notes": "pattern"}


def test_select_invalid_option() -> None:
    errs = validate_submission(SCHEMA, {"name": "x", "color": "purple", "accept": True})
    assert errs == {"color": "type"}


def test_checkbox_type() -> None:
    errs = validate_submission(SCHEMA, {"name": "x", "accept": "yes"})
    assert errs == {"accept": "type"}


def test_unknown_field() -> None:
    errs = validate_submission(SCHEMA, {"name": "x", "accept": True, "junk": 1})
    assert errs == {"junk": "unknown_field"}


def test_multi_step_field_collection() -> None:
    multi = {
        "title": "Multi",
        "steps": [
            {"blocks": [{"kind": "field", "name": "a", "type": "text", "label": "A", "required": True}]},
            {"blocks": [{"kind": "field", "name": "b", "type": "text", "label": "B", "required": True}]},
        ],
    }
    assert validate_submission(multi, {"a": "x", "b": "y"}) == {}
    assert validate_submission(multi, {"a": "x"}) == {"b": "required"}


def test_empty_optional_field_skipped() -> None:
    """Empty string in an optional field is not a type error."""
    errs = validate_submission(SCHEMA, {"name": "x", "email": "", "accept": True})
    assert errs == {}


def test_assertions_and_changeset_blocks_pass_through() -> None:
    """Eval review forms use `assertions` and `changeset` display blocks
    alongside regular fields. The validator must treat them as no-op
    display blocks (only `field` blocks contribute to value validation).
    """
    schema: dict[str, Any] = {
        "title": "Review eval results",
        "steps": [
            {
                "blocks": [
                    {"kind": "markdown", "content": "Review the run"},
                    {
                        "kind": "assertions",
                        "criteria": [
                            {"name": "c1", "status": "passed", "summary": "ok"},
                            {"name": "c2", "status": "failed", "summary": "missing detail"},
                        ],
                    },
                    {
                        "kind": "changeset",
                        "name": "review",
                        "files": [
                            {"path": "src/foo.ts", "status": "added", "additions": 5, "deletions": 0, "diff": "+ x"},
                        ],
                    },
                    {"kind": "field", "name": "commit_after", "type": "checkbox", "label": "Commit"},
                ]
            }
        ],
    }
    assert validate_submission(schema, {"commit_after": True}) == {}
    assert validate_submission(schema, {"commit_after": False}) == {}
    # Unknown field still flagged
    assert validate_submission(schema, {"commit_after": True, "bogus": 1}) == {"bogus": "unknown_field"}


def test_changeset_block_name_in_values_is_accepted() -> None:
    """The web `ChangesetBlock` writes its comments array under
    `values[block.name]`. The validator must treat that key as known —
    otherwise every submitted form with a changeset block returns 422
    `unknown_field` even though the data is well-formed (gh review-form
    422 regression).
    """
    schema: dict[str, Any] = {
        "title": "Review",
        "steps": [
            {
                "blocks": [
                    {
                        "kind": "changeset",
                        "name": "review",
                        "files": [],
                    },
                    {"kind": "field", "name": "commit_after", "type": "checkbox", "label": "Commit"},
                ]
            }
        ],
    }
    # The frontend submits `review` as an array of comment objects (may be empty).
    assert validate_submission(schema, {"commit_after": False, "review": []}) == {}
    assert (
        validate_submission(
            schema,
            {
                "commit_after": True,
                "review": [{"file": "src/foo.ts", "line": 5, "body": "rename x"}],
            },
        )
        == {}
    )
    # A genuinely unknown key still gets flagged.
    assert validate_submission(schema, {"commit_after": False, "review": [], "bogus": 1}) == {"bogus": "unknown_field"}
