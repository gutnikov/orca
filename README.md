<p align="center">
  <img src="docs/logo.png" width="300" alt="Orca">
</p>

<h1 align="center">Orca</h1>

Orca orchestrates fleets of AI agents that decompose, plan, build, and merge code — all defined as a YAML state machine with parallel workers and isolated git worktrees. One spec in, working code out.

![Orca TUI](docs/screenshots/tui.png)

## Features

- **Multi-stage YAML workflows** — define states, transitions, decomposition, and retries
- **Parallel agents in isolated git worktrees** — no merge conflicts between workers
- **Multiple worker backends** — Claude Code and OpenCode, with per-worker model and args
- **Typed issue flows** — different issue types with independent state machines
- **Concurrent runs** — multiple orca processes in the same repo via `-b`/`--base`
- **Human-in-the-loop** — Slack integration for agent-to-human conversations mid-workflow
- **Live TUI** — progress tree, session terminals, result badges, insights monitoring
- **Headless mode** — run without TUI for CI or background execution

## Install

```bash
pipx install "git+ssh://git@github.com/gutnikov/orca.git"
```

Update to latest:

```bash
pipx install --force "git+ssh://git@github.com/gutnikov/orca.git"
```

## Quick Start

Copy the example config into your repo and run:

```bash
cp -r example/* your-repo/
orca task.md
```

See [`example/`](example/) for the full setup — config, prompts, and a sample task file.

## Setup

### 1. Create a workflow config

Add `orca.yml` to your repo root. You can have multiple workflow files (e.g. `orca.develop.yml`, `orca.test.yml`) and select them with `-w`.

```yaml
issue:
  fields:
    title:
      type: string
      description: Issue title

initial: todo

states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/implement.md
      result_format:
        outcome:
          type: enum
          values: [complete, reject]
          description: Implementation result
        reason:
          type: string
          description: Why rejected
          required_when: [reject]
    on:
      complete: done
      reject: todo
```

### 2. Write worker prompts

Prompts are Jinja2 templates. See the [Writing Worker Prompts](docs/writing-prompts.md) guide for principles, mechanics, and a checklist. Create `prompts/implement.md`:

```markdown
You are working on: {{ issue.title }}

{{ issue.description }}

Implement this feature. When done, respond with your result.
```

### 3. Write a task file

A task file is plain text — first line is the title, rest is the description:

```
Add user authentication
Implement JWT-based auth with login, register, and token refresh endpoints.
```

Save it as `task.md` (or any filename).

### 4. Run it

```bash
orca task.md
```

Orca creates an integration branch from your current HEAD, then:
- Spawns a worktree per agent
- Routes each issue through the state machine
- Shows live progress in the TUI

For named runs (enables concurrent execution):

```bash
orca task.md -b feature-auth
```

## Options

| Flag | Description |
|------|-------------|
| `-w WORKFLOW` | Workflow shorthand. `-w develop` loads `orca.develop.yml`. Default: `orca.yml`. |
| `-b BRANCH` | Integration branch name. Enables concurrent run isolation. |
| `--base REF` | Base git ref to branch from. Requires `-b`. Default: config's `base_branch` or `origin/main`. |
| `--headless` | Run without TUI (headless mode). |
| `--insights` | Enable insights agent for progress monitoring. |

## Workflow features

**Transitions** — route issues to different states based on worker output:

```yaml
on:
  complete: done
  needs_review: reviewing
  reject: todo            # loops back for retry
```

**Decomposition** — a worker can break an issue into sub-issues:

```yaml
states:
  scoping:
    worker:
      kind: claude-code
      prompt: prompts/scope.md
      result_format:
        outcome:
          type: enum
          values: [decompose, implement]
        sub_issues:
          type: list
          items: "$issue"
          required_when: [decompose]
    on:
      decompose:
        action: decompose
        then: todo
      implement: implementing
```

**Worker backends** — use Claude Code or OpenCode as workers, with optional model and args overrides:

```yaml
states:
  implementing:
    worker:
      kind: opencode          # or claude-code
      prompt: prompts/implement.md
      model: gpt-4o           # optional model override
      args: ["--max-turns", "100"]  # additional CLI args
      timeout: 600            # inactivity timeout in seconds
```

**Serialized execution** — limit parallel workers per state:

```yaml
states:
  apply:
    max_workers: 1    # one at a time
```

**User feedback via Slack** — any worker can pause and ask the user a question. Add `needs_feedback` to a state's outcome values and the orchestrator handles the rest: it spawns a feedback agent that conducts a multi-turn Slack conversation, then re-dispatches the original worker with the answers. No `on:` rule needed — `needs_feedback` is a reserved outcome.

```yaml
states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implement.md
      result_format:
        outcome:
          type: enum
          values: [done, blocked, needs_feedback]
          values_description:
            done: "All tests pass, changes committed"
            blocked: "Cannot proceed"
            needs_feedback: "Need clarification from user"
        feedback_questions:
          type: string
          required_when: [needs_feedback]
    on:
      done: applying
      blocked: planning
      # needs_feedback has no on: rule — handled automatically
```

Requires `integrations.slack` in `orca.yml` (see Integrations below). Each feedback round counts toward `max_worker_retries`. The re-dispatched worker sees `{{ issue.feedback_context }}` in its prompt template.

**Timeouts and retries:**

```yaml
max_worker_retries: 3     # global retry limit (default: 5)

states:
  implementing:
    worker:
      timeout: 300        # seconds per worker run
    max_visits: 2         # max times an issue can enter this state
```

**Concurrent runs** — run multiple orca processes in the same repo, each isolated in its own integration branch:

```bash
orca task-auth.md -b feature-auth
orca task-billing.md -b feature-billing
```

Set the default base ref in config:

```yaml
base_branch: origin/main
```

**Typed issue flows** *(advanced)* — define multiple issue types with independent fields and state machines. Decomposed children can follow a different flow than their parent:

```yaml
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
```

The flat format (`issue:` / `states:` / `initial:` at the top level) is still supported and recommended for single-type workflows.

## Integrations

**Slack (Human-in-the-loop)** — Orca includes a built-in MCP server that lets workers conduct multi-turn Slack DM conversations with humans during workflow execution. Add to your `orca.yml`:

```yaml
integrations:
  slack:
    bot_token_env: SLACK_BOT_TOKEN
    app_token_env: SLACK_APP_TOKEN
```

Your Slack app needs Bot Token Scopes (`chat:write`, `im:write`) and an App-Level Token with `connections:write` (Socket Mode).

Slack powers two features:
- **Direct HITL** — workers call `slack_start_conversation` / `slack_wait_for_reply` tools directly in their prompt
- **`needs_feedback` outcome** — any worker can return `needs_feedback` to pause and trigger an automated feedback agent that talks to the user, then re-dispatches the worker with answers (see Workflow Features above)

**Insights** — pass `--insights` to spawn a monitoring agent that watches the pipeline for errors, loops, and slow workers, surfacing findings as interactive entries in the TUI.

## TUI keyboard shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh state and content pane |
| `n` | Retry failed issue |
| `h` / `l` or Left / Right | Focus tree / content panel |
| `j` / `k` | Scroll content down / up |

## Development

```bash
uv sync                        # install dependencies
uv run pytest                  # run tests
uv run ruff check .            # lint
uv run mypy src/               # type-check
```
