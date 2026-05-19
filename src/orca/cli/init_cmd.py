"""orca init — deprecated; playbooks are now served via the MCP tool."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def init_command(root: Path | None = None) -> None:
    """Print a deprecation notice and remove any leftover `.orca/playbooks/`.

    Since version 0.3.5, playbooks are served directly from the installed orca
    package via the `orca_get_playbook` MCP tool. `orca init` no longer copies
    files into the project. Re-running it cleans up any stale `.orca/playbooks/`
    directory left over from earlier orca versions.
    """
    from orca.cli.daemon_cmd import _repo_root

    repo = _repo_root(root)
    legacy = repo / ".orca" / "playbooks"

    message = (
        "orca init: playbooks are now served via the `orca_get_playbook` MCP "
        "tool. This command no longer copies files into your project."
    )

    if legacy.exists():
        shutil.rmtree(legacy)
        print(f"{message}\nRemoved legacy directory: {legacy}", file=sys.stderr)
        return

    print(message, file=sys.stderr)
