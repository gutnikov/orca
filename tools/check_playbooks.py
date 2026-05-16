#!/usr/bin/env python3
"""Static checks for the bundled playbook set.

Runs in CI and pre-commit. Validates:

1. Every markdown link with a `.md` target resolves to a file that exists.
2. No stray `..` link escapes the playbook tree (those break after `orca init`
   copies playbooks into `.orca/playbooks/` in user projects).

Exit code is non-zero if any check fails; output names the offending file and
the offending link so the failure is easy to locate.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAYBOOK_ROOT = REPO_ROOT / "src" / "orca" / "playbooks"

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)\)")


def check_links() -> list[str]:
    errors: list[str] = []
    for md in sorted(PLAYBOOK_ROOT.rglob("*.md")):
        text = md.read_text()
        for match in LINK_RE.finditer(text):
            target = match.group(2)
            if target.startswith(("http://", "https://", "#")):
                continue
            resolved = (md.parent / target).resolve()
            try:
                resolved.relative_to(PLAYBOOK_ROOT)
            except ValueError:
                rel = md.relative_to(REPO_ROOT)
                errors.append(
                    f"{rel}: link `{target}` escapes the playbook tree — "
                    f"would 404 after `orca init` copies playbooks into "
                    f"`.orca/playbooks/`. Use an https URL or a playbook-relative path."
                )
                continue
            if not resolved.exists():
                rel = md.relative_to(REPO_ROOT)
                errors.append(f"{rel}: broken link `{target}` (resolves to {resolved})")
    return errors


def main() -> int:
    if not PLAYBOOK_ROOT.is_dir():
        print(f"playbook root not found: {PLAYBOOK_ROOT}", file=sys.stderr)
        return 2

    errors = check_links()
    if errors:
        print(f"check_playbooks: {len(errors)} issue(s)\n", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    md_count = sum(1 for _ in PLAYBOOK_ROOT.rglob("*.md"))
    print(f"check_playbooks: OK ({md_count} files, all links resolve)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
