# Convenience Wrapper Skill — Template & Rules

A **wrapper skill** is a thin SKILL.md scaffolded into a user's project alongside an orca workflow, so anyone on the team can invoke the workflow with natural language ("fix this bug", "ship a feature") without knowing Orca exists. The wrapper composes a `task.md` from the user's ask and starts the run via the orca MCP tool — fire-and-forget. Supervision stays in the `orca-workflow-run` skill.

This doc is the source of truth for **what** to write and **where**, used by Step 9 of [`../orca-workflow-create.md`](../orca-workflow-create.md).

## When to use this

Offer a wrapper when:

- The workflow will be invoked repeatedly (not a one-shot exploration).
- More than one teammate will trigger it, or the original author wants to forget the `orca run` invocation themselves.
- The workflow has a clear, nameable input ("a bug to fix", "a feature spec to ship") — the wrapper's `description` needs concrete trigger phrases to route correctly.

Skip a wrapper when:

- The workflow is a one-off audit or experiment.
- The team doesn't use Claude Code or Codex (no host CLI to route from).

## Target paths (both, always)

Write the same SKILL.md content to **both** locations so the wrapper works in either host CLI:

| Host CLI | Path in user's repo | Discovery |
|---|---|---|
| Claude Code | `<repo>/.claude/skills/<name>/SKILL.md` | Auto-discovered. |
| Codex | `<repo>/.agents/skills/<name>/SKILL.md` | Auto-discovered (project scope; precedes user-level `~/.codex/skills/`). |

Both are checked into the repo so teammates pick them up on clone.

## Naming convention

- **Default:** the workflow's filename without `.yml`. `.orca/bugfix.yml` → wrapper named `bugfix`.
- Kebab-case, no spaces, no `orca-` prefix (the wrapper hides Orca, so don't tag it).
- The wrapper's `name:` frontmatter field MUST match the directory name.

## Description authoring (the load-bearing step)

The `description:` is the **only** thing the host CLI uses to decide whether to route to this wrapper. A weak description means the wrapper is dead weight — the user says "fix this bug", the host doesn't trigger the wrapper, the user has to invoke it by hand, and the whole abstraction breaks.

Rules:

1. **Lead with `"Use when..."`** — matches the style of every Orca skill description in this repo, so the host's routing model treats it the same way.
2. **Enumerate ≥3 concrete trigger phrases verbatim**, drawn from how the team actually talks. The host matches semantically, but concrete phrases tighten the match. Examples for a `bugfix` workflow:
   - "fix this bug"
   - "the login button doesn't work, investigate and fix"
   - "look into the flaky test in checkout"
3. **Name the action plainly** at the end ("kicks off the bugfix workflow" — but NOT "kicks off the bugfix orca workflow"; the wrapper hides Orca).
4. **Keep under ~80 words.** Longer descriptions get diluted in semantic matching.
5. **Don't mention Orca by name.** From the user's perspective, the wrapper *is* the feature.

Generate the description, show it to the user, and ask: *"Will your team naturally say any of these? Any phrases I missed?"* Iterate until they confirm.

## The template

Fill placeholders marked `<...>` from the workflow being created. The same rendered content goes to both target paths.

```markdown
---
name: <wrapper-name>
description: <authored per "Description authoring" above>
---

# <wrapper-name>

When this skill triggers:

1. Capture the user's natural-language ask in 1–2 sentences. If anything required by the workflow's issue schema is missing or ambiguous, ask one clarifying question — then stop asking.
2. Compose a `task.md` filling the workflow's required fields:
   - `<field-1>`: <one-line guidance, taken from the workflow's issue.fields block>
   - `<field-2>`: <one-line guidance>
   - <... one bullet per issue field>
3. Check the daemon. Call `orca_daemon_status`; if it reports the daemon is not running, tell the user to start it themselves with `orca daemon start` in a shell at the project root. Do not call `orca_start_run` until the daemon is up — it will return a clear error.
4. Write `task.md` at the project's existing convention — `task.md` at repo root, or under `input/`/`tasks/` if the project already uses one of those. Match what's already there.
5. Start the run via the MCP tool. The `workflow` argument is the workflow filename without `.yml` — that is `<workflow-file-stem>` below, **not** the wrapper-skill name (those usually match, but if the user renamed the wrapper they will not):
   ```
   orca_start_run(root="<absolute repo path>", task_file="<task-file path>", workflow="<workflow-file-stem>")
   ```
6. Report the `run_id` returned by the MCP tool to the user. Tell them they can ask to supervise it (which will route to the `orca-workflow-run` skill), or just wait for it to finish.

This is a thin wrapper. **Do not** inline supervision, retries, merge handling, or progress polling — that lives in the `orca-workflow-run` skill. Call `orca_start_run` exactly once and exit.
```

The wrapper deliberately uses the `orca_start_run` MCP tool rather than the `orca run` CLI — that's what the `orca-workflow-run` skill uses, and it avoids a shell hop. Both work; the MCP form is more uniform across host CLIs.

## `.gitignore` interaction

Some teams `.gitignore` `.agents/` or `.claude/` wholesale (treating them as scratch/local state). The wrapper needs to be checked in to reach teammates. After writing both files, grep the project's `.gitignore`:

- If `.claude/` or `.claude/skills/` is ignored: add `!.claude/skills/` (or a narrower exception for the wrapper directory) and surface this to the user.
- Same for `.agents/`.

Don't silently un-ignore — show the user the proposed `.gitignore` edit and ask.

## Anti-patterns

- **Generic `description:`** ("runs the bugfix workflow"). The host won't route to it. Always enumerate trigger phrases.
- **Mentioning Orca in the description.** The point of the wrapper is to hide Orca. If the team needs to know Orca exists to phrase a trigger, the wrapper failed.
- **Inlining supervision.** The wrapper is fire-and-forget. If the user wants the run watched, they (or the host) invoke `orca-workflow-run` separately. Don't duplicate the supervision logic — it will drift.
- **Bundling scripts or assets** in the wrapper directory. The wrapper is a single SKILL.md. If you need scripts, you need a real skill, not a wrapper.
- **Wrapping a workflow that doesn't have a clear input.** If the workflow takes a free-form task file and produces unpredictable output, there's no natural-language ask to trigger on, and the wrapper's `description` becomes mush.
