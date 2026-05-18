from collections.abc import Callable
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment, TemplateNotFound


class AbsolutePathLoader(BaseLoader):
    """Custom Jinja2 loader that loads templates by absolute file path."""

    def get_source(self, environment: Environment, template: str) -> tuple[str, str | None, Callable[[], bool]]:
        """Load template from absolute file path."""
        path = Path(template)

        if not path.exists():
            raise TemplateNotFound(template)

        source = path.read_text()
        return source, str(path), lambda: True


class TemplateRenderError(Exception):
    pass


_RESULT_FILE_WARNING_TEMPLATE = """

---

**IMPORTANT: Writing the result file at `{result_path}` is the final action of your session. \
The orchestrator will terminate this session shortly after detecting the result file. \
Complete ALL other work — git commits, file writes, code changes — before writing the result file.**"""

_PROGRESS_INSTRUCTION = """

---

## Progress Reporting

As you work, periodically report your progress by printing a progress line:

PROGRESS: <percent> | <status>

- `<percent>` is an integer from 0 to 100
- `<status>` is a short description of what you're currently doing
- Emit this after completing meaningful milestones, not on every action
- Example: PROGRESS: 25 | Exploring codebase structure"""


def _build_result_example(result_format: dict[str, Any]) -> dict[str, Any]:
    """Build a worker-facing example result from a result_format schema."""
    example: dict[str, Any] = {}
    for name, field in result_format.items():
        if not isinstance(field, dict):
            example[name] = None
            continue

        field_type = field.get("type")
        if field_type == "enum":
            values = field.get("values", [])
            example[name] = values[0] if values else ""
        elif field_type == "string":
            example[name] = f"<{name}>"
        elif field_type == "list":
            example[name] = []
        else:
            example[name] = None
    return example


def _build_context(
    issue: dict[str, Any],
    result_format: dict[str, Any],
    result_path: Path,
    run: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "issue": issue,
        "result_format": result_format,
        "result_example": _build_result_example(result_format),
        "result_path": str(result_path),
        "run": run,
    }


def _finalize(rendered: str, *, progress: bool, result_path: Path) -> str:
    if progress:
        rendered = _PROGRESS_INSTRUCTION + "\n\n---\n\n" + rendered
    return rendered + _RESULT_FILE_WARNING_TEMPLATE.format(result_path=str(result_path))


def render_prompt(
    template_path: Path,
    repo_root: Path,
    issue: dict[str, Any],
    result_format: dict[str, Any],
    result_path: Path,
    *,
    progress: bool = False,
    run: dict[str, Any] | None = None,
) -> str:
    """Render a Jinja2 template from a file with issue context and output rules.

    Args:
        template_path: Absolute path to the template file.
        repo_root: Root directory of the repository (unused but kept for API consistency).
        issue: Dictionary containing issue data (fields, event_log, children, etc.).
        result_format: Dictionary describing output field format.
        result_path: Path where the result will be written.

    Returns:
        Rendered template as a string.

    Raises:
        FileNotFoundError: If the template file does not exist.
    """
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    env = Environment(
        loader=AbsolutePathLoader(),
        autoescape=False,  # No auto-escaping for markdown
    )

    template = env.get_template(str(template_path))
    context = _build_context(issue, result_format, result_path, run)

    try:
        rendered = template.render(context)
    except Exception as exc:
        msg = (
            f"Failed to render prompt template {template_path}: {exc}. "
            "If you are accessing dict keys that may shadow Python methods, "
            "use bracket syntax such as result_format['outcome']['values']."
        )
        raise TemplateRenderError(msg) from exc
    return _finalize(rendered, progress=progress, result_path=result_path)


def render_prompt_string(
    template_source: str,
    issue: dict[str, Any],
    result_format: dict[str, Any],
    result_path: Path,
    *,
    progress: bool = False,
    run: dict[str, Any] | None = None,
) -> str:
    """Render an inline Jinja2 template string with issue context and output rules.

    Mirrors `render_prompt` but accepts the template source directly instead of a file path.
    """
    env = Environment(autoescape=False)
    template = env.from_string(template_source)
    context = _build_context(issue, result_format, result_path, run)

    try:
        rendered = template.render(context)
    except Exception as exc:
        msg = (
            f"Failed to render inline prompt template: {exc}. "
            "If you are accessing dict keys that may shadow Python methods, "
            "use bracket syntax such as result_format['outcome']['values']."
        )
        raise TemplateRenderError(msg) from exc
    return _finalize(rendered, progress=progress, result_path=result_path)
