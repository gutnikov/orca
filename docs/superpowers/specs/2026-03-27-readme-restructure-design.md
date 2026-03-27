# README Restructure Design

**Date:** 2026-03-27
**Goal:** Rewrite README.md targeting new users discovering the project, reflecting all features added since initial release.

## Audience

New users evaluating whether orca fits their needs. The README should let them quickly understand what orca does, get running with a minimal setup, then progressively discover advanced features.

## Structure

```
Logo + tagline (unchanged)
TUI screenshot (unchanged)
Features (new — scannable bullet list)
Install (unchanged)
Quick Start (renamed from "Example")
Setup (4-step, unchanged structure)
Options (updated CLI table)
Workflow Features
  - Transitions (existing)
  - Decomposition (existing)
  - Worker backends (new)
  - Serialized execution (existing)
  - Timeouts and retries (existing)
  - Concurrent runs (new)
  - Typed issue flows (new, advanced)
Integrations (new)
  - Slack HITL (brief + link)
  - Insights (one-liner)
TUI keyboard shortcuts (unchanged)
Development (unchanged)
```

## Section Details

### Features

Eight bullet points placed immediately after the TUI screenshot. Gives a quick "what can it do" scan:

- Multi-stage YAML workflows — states, transitions, decomposition, retries
- Parallel agents in isolated git worktrees
- Multiple worker backends — Claude Code and OpenCode, with per-worker model and args
- Typed issue flows — different issue types with independent state machines
- Concurrent runs — multiple orca processes in the same repo
- Human-in-the-loop — Slack integration for agent-to-human conversations
- Live TUI — progress tree, session terminals, result badges, insights
- Headless mode for CI or background execution

### Install

Unchanged. `pipx install` and `pipx install --force` for update.

### Quick Start

Rename "Example" to "Quick Start". Keep brief:

```bash
cp -r example/* your-repo/
orca task.md
```

Link to `example/` for full setup.

### Setup

Same 4 steps:

1. Create workflow config — keep the minimal `orca.yml` snippet (single-state)
2. Write worker prompts — unchanged Jinja2 example
3. Write a task file — unchanged
4. Run it — add brief mention of `-b` for named runs

### Options

Updated table with all current CLI flags:

| Flag | Description |
|------|-------------|
| `-w WORKFLOW` | Workflow shorthand. `-w develop` loads `orca.develop.yml`. Default: `orca.yml`. |
| `-b BRANCH` | Integration branch name. Enables concurrent run isolation. |
| `--base REF` | Base git ref to branch from. Requires `-b`. Default: config's `base_branch` or `origin/main`. |
| `--headless` | Run without TUI, log to file. |
| `--insights` | Enable live progress monitoring agent. |

### Workflow Features

#### Transitions (existing)

Unchanged — route issues based on worker output.

#### Decomposition (existing)

Unchanged — workers can break issues into sub-issues.

#### Worker backends (new)

Show that workers support `claude-code` and `opencode`, with optional `model` and `args` overrides:

```yaml
worker:
  kind: opencode
  prompt: prompts/implement.md
  model: gpt-4o
  args: ["--max-turns", "100"]
```

#### Serialized execution (existing)

Unchanged — `max_workers: 1`.

#### Timeouts and retries (existing)

Unchanged, but verify the config keys still match current code.

#### Concurrent runs (new)

Multiple orca processes in the same repo, each isolated:

```bash
orca task-auth.md -b feature-auth
orca task-billing.md -b feature-billing
```

Config default: `base_branch: origin/main`.

#### Typed issue flows (new, advanced)

Brief explanation that different issue types can have independent fields and state machines. Compact example showing `root_type`, `types:` map, `child_type` on decompose transitions. Note that the flat format is still supported.

### Integrations (new)

#### Slack (Human-in-the-loop)

Brief description: built-in MCP server for agent-to-human Slack DM conversations. Show minimal config:

```yaml
integrations:
  slack:
    bot_token_env: SLACK_BOT_TOKEN
    app_token_env: SLACK_APP_TOKEN
```

Link to detailed docs for Slack app setup.

#### Insights

One sentence: `--insights` spawns a monitoring agent that watches for errors, loops, and slow workers, surfacing findings in the TUI.

### TUI keyboard shortcuts

Unchanged.

### Development

Unchanged.

## What's NOT changing

- Logo, tagline, screenshot
- Install commands
- Minimal orca.yml snippet in Setup (progressive disclosure — simple first)
- Example directory (audited, parses fine with current code)
- TUI shortcuts table
- Development commands

## Decisions

- **Lead with flat format, typed flows as advanced** — easier onboarding for new users
- **Slack HITL and Insights are brief mentions** — link to docs, don't bloat README
- **No example directory changes** — it works as-is, serves the "get started" purpose
- **Feature list up top** — lets newcomers quickly assess capabilities before diving into config
