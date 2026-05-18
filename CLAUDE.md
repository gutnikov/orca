# Orca repo conventions

## Playbook naming

Playbooks under `src/orca/playbooks/` follow the pattern:

```
orca-{item}-{action}.md
```

Examples: `orca-workflow-create.md`, `orca-workflow-run.md`, `orca-workflow-review.md`, `orca-prompt-create.md`.

Rules:
- `{item}` is the noun the playbook operates on (e.g. `workflow`, `prompt`). It may be multi-word (`state-prompt`) if needed, but prefer a single word.
- `{action}` is the verb (e.g. `create`, `run`, `review`, `audit`). One word, imperative.
- Action-only playbooks with no clear item (e.g. `orca-install.md`) are exempt.
- Descriptive reference docs under `playbooks/reference/` (glossary, schema reference, pattern catalogue) are not action playbooks and are exempt from this pattern.

When adding a new playbook, also update any SKILL.md that lists "required reading", and run `python3 tools/check_playbooks.py` to verify links resolve.

## Version bumping

Orca's version lives in **four** files. They must all be bumped together — bumping only `pyproject.toml` will silently fail to publish (the Claude Code and Codex plugin update CLIs read the plugin manifests, not the Python package version).

| File | Field |
|---|---|
| `pyproject.toml` | `version = "X.Y.Z"` (top-level `[project]`) |
| `.claude-plugin/marketplace.json` | `plugins[0].version` |
| `plugin/orca/.claude-plugin/plugin.json` | `version` (Claude Code plugin manifest) |
| `plugins/orca/.codex-plugin/plugin.json` | `version` (Codex plugin manifest) |

Procedure:

1. Bump all four files to the new version in one commit (typical message: `chore: bump version to X.Y.Z`).
2. Run `uv lock` to regenerate `uv.lock` — it picks up the new package version automatically. Stage and commit the lock-file change alongside (single commit is fine).
3. Verify: `grep -rn '"version"\|^version' --include="*.json" --include="*.toml" plugin/ plugins/ pyproject.toml .claude-plugin/marketplace.json` — all four lines should show the new version.
4. Push to `origin/main`. Installed plugins pick up the new version via `claude plugin update orca@orca` (and the Codex equivalent).

Notes:

- `claude plugin tag` validates that `.claude-plugin/marketplace.json` and `plugin/orca/.claude-plugin/plugin.json` agree — if you ever skip one, that check will catch it.
- `.agents/plugins/marketplace.json` has no version field; ignore it for version bumps.
- The plugin manifests do NOT auto-derive from `pyproject.toml`. Always edit by hand.
