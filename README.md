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

**Worker-driven HITL** — any worker can talk to users directly using communication MCP tools (Slack, email, etc.). Instruct the worker in its prompt to ask when blocked, and set a longer timeout to accommodate human response time:

```yaml
states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implement.md
      timeout: 3600                  # 60 min — allows human interaction
      result_format:
        outcome:
          type: enum
          values: [done, blocked]
    on:
      done: applying
      blocked: planning
```

In the worker prompt:
```
If you need clarification from the user, use the slack_start_conversation
and slack_wait_for_reply tools to ask them directly. Do not report blocked
for questions the user can answer.
```

Workers discover MCP tools from the project's `.mcp.json` — orca doesn't need to know which communication channel is used.

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

**Slack** — Workers can conduct multi-turn Slack DM conversations during execution using the `slack-hitl` MCP server. Configure it in your project's `.mcp.json` and instruct workers in their prompts to use the tools when they need human input.

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
