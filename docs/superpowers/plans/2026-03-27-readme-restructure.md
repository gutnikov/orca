# README Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite README.md to target new users discovering the project, with a features overview up front and progressive disclosure of advanced features.

**Architecture:** Single-file rewrite of `README.md`. No code changes, no new files. The structure flows: hero → features → install → quick start → setup → options → workflow features → integrations → TUI → development.

**Tech Stack:** Markdown

---

### Task 1: Features section + Quick Start rename

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Features section after TUI screenshot**

Insert immediately after the `![Orca TUI]` line:

```markdown
## Features

- **Multi-stage YAML workflows** — define states, transitions, decomposition, and retries
- **Parallel agents in isolated git worktrees** — no merge conflicts between workers
- **Multiple worker backends** — Claude Code and OpenCode, with per-worker model and args
- **Typed issue flows** — different issue types with independent state machines
- **Concurrent runs** — multiple orca processes in the same repo via `-b`/`--base`
- **Human-in-the-loop** — Slack integration for agent-to-human conversations mid-workflow
- **Live TUI** — progress tree, session terminals, result badges, insights monitoring
- **Headless mode** — run without TUI for CI or background execution
```

- [ ] **Step 2: Rename "Example" to "Quick Start"**

Change the `## Example` heading to `## Quick Start`. Update the text to:

```markdown
## Quick Start

Copy the example config into your repo and run:

\`\`\`bash
cp -r example/* your-repo/
orca task.md
\`\`\`

See [`example/`](example/) for the full setup — config, prompts, and a sample task file.
```

- [ ] **Step 3: Verify the markdown renders correctly**

Run: `cat README.md | head -40` to verify structure.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add features section and rename example to quick start"
```

---

### Task 2: Update Setup step 4 and Options table

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update "Run it" step to mention `-b`**

In section "### 4. Run it", replace the current content with:

```markdown
### 4. Run it

\`\`\`bash
orca task.md
\`\`\`

Orca creates an integration branch from your current HEAD, then:
- Spawns a worktree per agent
- Routes each issue through the state machine
- Shows live progress in the TUI

For named runs (enables concurrent execution):

\`\`\`bash
orca task.md -b feature-auth
\`\`\`
```

- [ ] **Step 2: Update the Options table**

Replace the current Options table with the full set of CLI flags:

```markdown
## Options

| Flag | Description |
|------|-------------|
| `-w WORKFLOW` | Workflow shorthand. `-w develop` loads `orca.develop.yml`. Default: `orca.yml`. |
| `-b BRANCH` | Integration branch name. Enables concurrent run isolation. |
| `--base REF` | Base git ref to branch from. Requires `-b`. Default: config's `base_branch` or `origin/main`. |
| `--headless` | Run without TUI (headless mode). |
| `--insights` | Enable insights agent for progress monitoring. |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update setup run step and options table with new CLI flags"
```

---

### Task 3: Add Worker backends and Concurrent runs sections

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Worker backends subsection**

After the existing "Decomposition" content in "Workflow features", add:

```markdown
**Worker backends** — use Claude Code or OpenCode as workers, with optional model and args overrides:

\`\`\`yaml
states:
  implementing:
    worker:
      kind: opencode          # or claude-code
      prompt: prompts/implement.md
      model: gpt-4o           # optional model override
      args: ["--max-turns", "100"]  # additional CLI args
      timeout: 600            # inactivity timeout in seconds
\`\`\`
```

- [ ] **Step 2: Add Concurrent runs subsection**

After "Timeouts and retries", add:

```markdown
**Concurrent runs** — run multiple orca processes in the same repo, each isolated in its own integration branch:

\`\`\`bash
orca task-auth.md -b feature-auth
orca task-billing.md -b feature-billing
\`\`\`

Set the default base ref in config:

\`\`\`yaml
base_branch: origin/main
\`\`\`
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add worker backends and concurrent runs sections"
```

---

### Task 4: Add Typed issue flows section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Typed issue flows subsection**

After "Concurrent runs", add:

```markdown
**Typed issue flows** *(advanced)* — define multiple issue types with independent fields and state machines. Decomposed children can follow a different flow than their parent:

\`\`\`yaml
root_type: epic

types:
  epic:
    fields:
      title: {type: string, description: "Title"}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scope.md
          result_format:
            outcome:
              type: enum
              values: [ready, decompose]
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
        on:
          ready: done
          decompose:
            action: decompose
            child_type: task    # children use a different type
            then: done
      done:
        terminal: true

  task:
    fields:
      title: {type: string, description: "Title"}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/impl.md
          result_format:
            outcome:
              type: enum
              values: [done]
        on:
          done: done
      done:
        terminal: true
\`\`\`

The flat format (`issue:` / `states:` / `initial:` at the top level) is still supported and recommended for single-type workflows.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add typed issue flows section"
```

---

### Task 5: Add Integrations section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Integrations section**

Insert a new `## Integrations` section between "Workflow features" and "TUI keyboard shortcuts":

```markdown
## Integrations

**Slack (Human-in-the-loop)** — Orca includes a built-in MCP server that lets workers conduct multi-turn Slack DM conversations with humans during workflow execution. Add to your `orca.yml`:

\`\`\`yaml
integrations:
  slack:
    bot_token_env: SLACK_BOT_TOKEN
    app_token_env: SLACK_APP_TOKEN
\`\`\`

Your Slack app needs Bot Token Scopes (`chat:write`, `im:write`) and an App-Level Token with `connections:write` (Socket Mode).

**Insights** — pass `--insights` to spawn a monitoring agent that watches the pipeline for errors, loops, and slow workers, surfacing findings as interactive entries in the TUI.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add integrations section (slack HITL, insights)"
```

---

### Task 6: Final review and cleanup

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the full README and verify structure**

Read the entire file and verify the section order matches the spec:

```
Logo + tagline
TUI screenshot
Features
Install
Quick Start
Setup (4 steps)
Options
Workflow features (transitions, decomposition, worker backends, serialized, timeouts, concurrent runs, typed flows)
Integrations (slack, insights)
TUI keyboard shortcuts
Development
```

- [ ] **Step 2: Fix any formatting issues**

Check for:
- Consistent heading levels (## for top sections, ### for subsections within Setup only, **bold** for workflow feature items)
- No double blank lines
- Code blocks have language tags
- Links work

- [ ] **Step 3: Commit any fixes**

```bash
git add README.md
git commit -m "docs: final README cleanup and formatting"
```
