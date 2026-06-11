#!/usr/bin/env python3
"""Static checks for the bundled playbook set and plugin skill markdown.

Runs in CI and pre-commit. Validates:

1. Every markdown link with a `.md` target resolves to a file that exists.
2. Inside the bundled playbook tree, no stray `..` link escapes it. Such
   links break the `orca_get_playbook` MCP tool: the tool resolves names
   relative to the bundled `orca.playbooks` package and rejects `..`
   traversal as unsafe, so an agent following such a link cannot reach
   the target.
3. Inside the plugin skill trees (`plugin/orca/skills/*` and
   `plugins/orca/skills/*`), markdown link targets must exist relative to
   the file they appear in. Cross-repo links (e.g. `../../../../src/...`)
   are flagged: when the skill ships inside an installed plugin, that
   relative path no longer resolves. Point at an `orca_get_playbook` call
   or an https URL instead.

Exit code is non-zero if any check fails; output names the offending file
and the offending link so the failure is easy to locate.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAYBOOK_ROOT = REPO_ROOT / "src" / "orca" / "playbooks"
PLUGIN_SKILL_ROOTS = (
    REPO_ROOT / "plugin" / "orca" / "skills",
    REPO_ROOT / "plugins" / "orca" / "skills",
)

# Group 2 is the .md path with any `#fragment` suffix already stripped, so
# anchored links like `[x](foo.md#section)` are validated too.
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)#]+\.md)(?:#[^)]*)?\)")


def _check_links_under(root: pathlib.Path, *, enforce_no_escape: bool) -> list[str]:
    """Scan every `*.md` under ``root`` for unresolved or escaping links.

    When ``enforce_no_escape`` is True (the bundled playbook tree), any link
    that resolves above ``root`` is reported — those break `orca_get_playbook`.
    When False (plugin skill trees), `..`-relative links are allowed within
    the repo checkout but flagged if they resolve to a missing file.
    """
    errors: list[str] = []
    if not root.is_dir():
        return errors
    for md in sorted(root.rglob("*.md")):
        text = md.read_text()
        for match in LINK_RE.finditer(text):
            target = match.group(2)
            if target.startswith(("http://", "https://", "#")):
                continue
            resolved = (md.parent / target).resolve()
            if enforce_no_escape:
                try:
                    resolved.relative_to(root)
                except ValueError:
                    rel = md.relative_to(REPO_ROOT)
                    errors.append(
                        f"{rel}: link `{target}` escapes the playbook tree — "
                        f"the `orca_get_playbook` MCP tool resolves names "
                        f"relative to the bundled `orca.playbooks` package and "
                        f"rejects `..` traversal as unsafe. Use an https URL or "
                        f"a playbook-relative path."
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

    errors: list[str] = []
    errors.extend(_check_links_under(PLAYBOOK_ROOT, enforce_no_escape=True))
    for plugin_root in PLUGIN_SKILL_ROOTS:
        errors.extend(_check_links_under(plugin_root, enforce_no_escape=False))

    if errors:
        print(f"check_playbooks: {len(errors)} issue(s)\n", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    scanned_roots = [PLAYBOOK_ROOT, *[r for r in PLUGIN_SKILL_ROOTS if r.is_dir()]]
    md_count = sum(sum(1 for _ in r.rglob("*.md")) for r in scanned_roots)
    print(f"check_playbooks: OK ({md_count} files, all links resolve)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
