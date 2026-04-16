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


_RESULT_FILE_WARNING = """

---

**IMPORTANT: Writing the result file is the final action of your session. \
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
    """Render a Jinja2 template with issue context and output rules.

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

    context = {
        "issue": issue,
        "result_format": result_format,
        "result_path": str(result_path),
        "run": run,
    }

    rendered = template.render(context)
    if progress:
        rendered = _PROGRESS_INSTRUCTION + "\n\n---\n\n" + rendered
    return rendered + _RESULT_FILE_WARNING
