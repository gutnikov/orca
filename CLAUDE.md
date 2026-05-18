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
