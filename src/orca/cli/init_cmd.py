"""orca init — copy reference docs into .orca/reference/."""

from __future__ import annotations

import shutil
from pathlib import Path


def init_command(root: Path | None = None) -> None:
    """Copy bundled reference docs into .orca/reference/."""
    from orca.cli.daemon_cmd import _repo_root

    repo = _repo_root(root)
    ref_src = Path(__file__).resolve().parent.parent / "reference"
    ref_dst = repo / ".orca" / "reference"
    ref_dst.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src_file in ref_src.glob("*.md"):
        shutil.copy2(src_file, ref_dst / src_file.name)
        copied += 1

    print(f"Copied {copied} reference docs to {ref_dst}")
