# Task File Parser Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix task file parser to handle YAML-formatted task files, extracting structured fields instead of treating raw YAML lines as plain text.

**Architecture:** `parse_task_file` gains YAML detection: if the content parses as a YAML dict, return its fields directly. Otherwise fall back to the existing first-line/rest-of-file split. The return type changes from `tuple[str, str]` to `dict[str, Any]`, and the caller builds issue fields from the dict instead of hardcoding `title`/`description`.

**Tech Stack:** Python 3.12, PyYAML (already a dependency via orca.yml parsing)

---

### Task 1: Update `parse_task_file` to support YAML

**Files:**
- Modify: `src/orca/orchestrator/runner.py:39-49`
- Test: `tests/orchestrator/test_runner.py`

- [ ] **Step 1: Write failing tests for YAML format**

Add to `tests/orchestrator/test_runner.py`:

```python
def test_parse_yaml_fields(self, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("title: ai-team\ndescription: AI team features\nscreen_paths:\n  - src/screens/ai-team/\n  - src/modules/AiTeam/\n")
    fields = parse_task_file(task)
    assert fields == {
        "title": "ai-team",
        "description": "AI team features",
        "screen_paths": ["src/screens/ai-team/", "src/modules/AiTeam/"],
    }

def test_parse_yaml_title_only(self, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("title: Simple fix\n")
    fields = parse_task_file(task)
    assert fields == {"title": "Simple fix"}

def test_parse_yaml_with_frontmatter_delimiters(self, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("---\ntitle: ai-team\ndescription: AI team features\n---\n")
    fields = parse_task_file(task)
    assert fields == {"title": "ai-team", "description": "AI team features"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_runner.py -v`
Expected: 3 new tests FAIL (return type is tuple, not dict)

- [ ] **Step 3: Update existing tests for new return type**

The existing tests expect `tuple[str, str]`. Update them to expect `dict[str, Any]`:

```python
def test_parse_title_and_description(self, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("Implement auth\nThis feature should support OAuth2\nand JWT tokens.")
    fields = parse_task_file(task)
    assert fields == {"title": "Implement auth", "description": "This feature should support OAuth2\nand JWT tokens."}

def test_title_only(self, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("Simple fix")
    fields = parse_task_file(task)
    assert fields == {"title": "Simple fix", "description": ""}

def test_strips_whitespace(self, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("  Title with spaces  \n  Description  ")
    fields = parse_task_file(task)
    assert fields == {"title": "Title with spaces", "description": "Description"}
```

- [ ] **Step 4: Implement `parse_task_file`**

Replace in `src/orca/orchestrator/runner.py`:

```python
def parse_task_file(path: Path) -> dict[str, Any]:
    """Read a task file and return issue fields as a dict.

    Supports two formats:
    - YAML: if content parses as a YAML dict, return its fields directly.
      Optional ``---`` frontmatter delimiters are stripped before parsing.
    - Plain text (legacy): first line is the title, remainder is the description.
    """
    text = path.read_text()

    # Strip optional frontmatter delimiters
    stripped = text.strip()
    if stripped.startswith("---"):
        lines = stripped.split("\n", 1)
        body = lines[1] if len(lines) > 1 else ""
        # Remove closing delimiter if present
        if "\n---" in body:
            body = body[: body.index("\n---")]
        parsed = yaml.safe_load(body)
    else:
        parsed = yaml.safe_load(text)

    if isinstance(parsed, dict):
        return {k: v for k, v in parsed.items() if v is not None}

    # Legacy plain-text fallback: first line = title, rest = description
    lines = text.split("\n", 1)
    title = lines[0].strip()
    description = lines[1].strip() if len(lines) > 1 else ""
    return {"title": title, "description": description}
```

- [ ] **Step 5: Add `Any` import if missing**

Ensure `from typing import Any` is present at the top of `runner.py`.

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/orchestrator/test_runner.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/runner.py tests/orchestrator/test_runner.py
git commit -m "fix: parse task files as YAML instead of plain text"
```

---

### Task 2: Update caller to use dict return

**Files:**
- Modify: `src/orca/orchestrator/runner.py:287-365`

- [ ] **Step 1: Update `run()` to use dict fields**

In `src/orca/orchestrator/runner.py`, change the caller at line 287:

From:
```python
title, description = parse_task_file(task_file)
```

To:
```python
fields = parse_task_file(task_file)
```

And at line 365, change:

From:
```python
fields = {"title": title, "description": description}
```

To:
```python
# fields already populated from parse_task_file
```

Remove the `title, description` destructuring and use `fields` directly in the `CreateEvent`.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 3: Run type checker**

Run: `uv run mypy src/`
Expected: No errors

- [ ] **Step 4: Run linter**

Run: `uv run ruff check .`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "refactor: use dict fields from parse_task_file in run()"
```

---

### Task 3: Update branch name derivation

**Files:**
- Modify: `src/orca/orchestrator/runner.py` (the `main()` function that derives branch name from title)

- [ ] **Step 1: Check how branch name is derived**

Find where `title` is used to derive the branch name. It may reference the old `title` variable. Update to use `fields.get("title", "untitled")`.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v && uv run mypy src/ && uv run ruff check .`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "fix: derive branch name from fields dict"
```
