<p align="center">
  <img src="docs/logo.png" width="300" alt="Orca">
</p>

<h1 align="center">Orca</h1>

Orca orchestrates fleets of AI agents that decompose, plan, build, and merge code — all defined as a YAML state machine with parallel workers and isolated git worktrees. One spec in, working code out.

![Orca TUI](docs/screenshots/tui.png)

## Prerequisites

Install [OpenCode](https://opencode.ai):

```bash
curl -fsSL https://opencode.ai/install | bash
```

Log in to your provider using OpenCode and choose a preferred model.

## Install

```bash
./setup.sh
```

The setup script will guide you through configuration interactively.

## Example

See [`example/`](example/) for a complete working setup — config, prompts, and a sample task file. Copy it into your repo to get started:

```bash
cp -r example/* your-repo/
```

## Quick start

### 1. Run it

```bash
orca task.md
```

Orca uses the current git branch as the base, then:
- Spawns a worktree per agent
- Routes each issue through the state machine
- Shows live progress in the TUI

### 2. Options

| Flag | Description |
|------|-------------|
| `-w WORKFLOW` | Workflow shorthand. `-w develop` loads `orca.develop.yml`. Default: `orca.yml`. |
| `--headless` | Run without TUI, log to file. |
| `--insights` | Enable progress monitoring agent. |

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

**Serialized execution** — limit parallel workers per state:

```yaml
states:
  apply:
    max_workers: 1    # one at a time
```

**Timeouts and retries:**

```yaml
max_worker_retries: 3     # global retry limit (default: 5)

states:
  implementing:
    worker:
      timeout: 300        # seconds per worker run
    max_visits: 2         # max times an issue can enter this state
```

## TUI keyboard shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh content pane |
| `n` | Retry failed issue |
| `h` / `l` or Left / Right | Focus tree / content panel |
| `j` / `k` | Scroll content down / up |
