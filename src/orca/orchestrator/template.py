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


def render_prompt(
    template_path: Path,
    repo_root: Path,
    issue: dict[str, Any],
    result_format: dict[str, Any],
    result_path: Path,
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
    }

    return template.render(context)


def render_insights_prompt(
    template_path: Path,
    state: dict[str, Any],
    transcripts: dict[str, str],
    mode: str,
    insights_so_far: str,
    output_path: str,
) -> str:
    """Render the insights prompt template."""
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    env = Environment(
        loader=AbsolutePathLoader(),
        autoescape=False,
    )

    template = env.get_template(str(template_path))

    context = {
        "state": state,
        "transcripts": transcripts,
        "mode": mode,
        "insights_so_far": insights_so_far,
        "output_path": output_path,
    }

    return template.render(context)
