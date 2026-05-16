"""orca init — copy playbooks into .orca/playbooks/."""

from __future__ import annotations

import shutil
from pathlib import Path


def init_command(root: Path | None = None) -> None:
    """Copy bundled playbooks into .orca/playbooks/, preserving subdirectories."""
    from orca.cli.daemon_cmd import _repo_root

    repo = _repo_root(root)
    src = Path(__file__).resolve().parent.parent / "playbooks"
    dst = repo / ".orca" / "playbooks"
    dst.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src_file in src.rglob("*.md"):
        rel = src_file.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, out)
        copied += 1

    print(f"Copied {copied} playbooks to {dst}")
