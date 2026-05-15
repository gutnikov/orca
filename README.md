# Orca

Orca is a coding agent orchestrator. Built for harness engineering and long-running flows.

- **Coding agents** — Claude Code and OpenCode as workers
- **TUI** — live terminal dashboard with issue trees, worker terminals, progress bars, and session history
- **MCP** — full API exposed as MCP tools so your coding agent can start, monitor, and control runs

One YAML config defines the workflow. Orca spawns agents in isolated git worktrees, routes results through a state machine, decomposes large tasks into parallel sub-issues, and handles retries, timeouts, and crash recovery. One spec in, working code out.

## Install as a Claude Code plugin

This repo is also a Claude Code plugin marketplace. Add it once, then install the `orca` plugin to get:

- `/orca:setup` — runs the One-Prompt Setup below for you, end-to-end
- `/orca:supervisor` — supervise a live run interactively (see `prompts/supervisor.md`)
- `/orca:create-workflow` — build, update, or audit `.orca/*.yml` workflows
- MCP server pre-registered (no manual `.mcp.json` needed)
- SessionStart hook that ensures the daemon is running in any `.orca`-enabled project

In Claude Code:

```
/plugin marketplace add gutnikov/orca
/plugin install orca@orca
```

Then run `/orca:setup` in any repo to bootstrap Orca. You still need the `orca` CLI itself — the `/orca:setup` command will `pipx install` it on first run.

## One-Prompt Setup

Copy this prompt into your coding agent (Claude Code, Cursor, Windsurf, etc.) to set up Orca in your project end-to-end. Prefer doing it manually? Skip to [Manual Setup](#manual-setup).

The prompt will:

1. Install orca via pipx
2. Start the daemon
3. Add `.orca-state/` to `.gitignore`
4. Create `.mcp.json` for MCP access
5. Download workflow reference docs into `.orca/reference/`
6. Create a starter workflow (`.orca/default.yml`) and prompt (`.orca/prompts/implement.md`)
7. Create a test task and run it

```
task.md ──► .orca/default.yml ──► implementing ──► done
                                       │
                                       ▼
                                  claude-code
                              (prompts/implement.md)
```

<blockquote>

**Set up Orca in this project.** Follow these steps in order:

**1. Install Orca** (skip if already installed — check with `which orca`):

```bash
pipx install "git+ssh://git@github.com/gutnikov/orca.git"
```

Verify: `orca -v` should print a version hash.

**2. Start the daemon** in this repo:

```bash
orca daemon start
```

Verify: `orca daemon status` should show it running.

**3. Add `.orca-state/` to `.gitignore`** (if not already there) — this is where Orca stores runtime data, logs, and worktrees:

```bash
echo '.orca-state/' >> .gitignore
```

**4. Create `.mcp.json`** in the project root to manage Orca runs via MCP:

```json
{
  "mcpServers": {
    "orca": {
      "command": "orca",
      "args": ["mcp"]
    }
  }
}
```

After creating the file, **tell me to reload MCP servers** (e.g. `/mcp` then restart, or `reload-plugins` depending on the client). Then verify the orca tools are available by calling `orca_daemon_status` with `root` set to this project's absolute path.

**5. Set up the `.orca/` directory** with workflow reference docs and a starter workflow:

```bash
mkdir -p .orca/prompts
```

Copy the bundled Orca workflow reference docs into `.orca/reference/` — these teach coding agents how to build and audit workflows:

```bash
orca init
```

Write `.orca/default.yml`:

```yaml
issue:
  fields:
    title:
      type: string
      description: "What to build"
    description:
      type: string
      description: "Detailed requirements"

initial: implementing

states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implement.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Implementation result"
    on:
      done: done
```

Write `.orca/prompts/implement.md`:

````markdown
# Implementing Agent

You are an implementation agent working in an isolated git worktree.

## Task

**{{ issue.fields.title }}**

{{ issue.fields.description }}

## Instructions

1. Read and understand the requirements
2. Implement the changes
3. Run any existing tests to make sure nothing is broken
4. Commit your changes with a descriptive message

## Output

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
````

**6. Create a task file** `task.md`:

```yaml
---
title: Add a hello endpoint
description: |
  Create a file called hello.py with a function greet(name)
  that returns "Hello, {name}!". Include a test in test_hello.py.
---
```

**7. Start a test run** using the MCP tools:

```
orca_start_run(root="<absolute path to this repo>", task_file="task.md")
```

Monitor it with `orca_get_run`. If anything fails, check `orca_get_worker_log`, fix the workflow or prompts, `orca_drop_run` the failed run, and retry.

</blockquote>

After the agent completes the setup, you can manage runs from the CLI (`orca tui`, `orca runs`, `orca logs`) or keep using MCP through your coding agent.

The `.orca/reference/` directory stays in your repo — whenever you need to evolve your workflow, just tell your agent: *"Read `.orca/reference/` and then [add a review stage / split implementing into plan+implement / audit my workflow]."* The reference docs teach the agent the full Orca config schema, prompt patterns, and validation rules.

See the rest of this README for the full reference.

---

## Manual Setup

Already set up with the [One-Prompt Setup](#one-prompt-setup)? Skip to [How It Works](#how-it-works).

### 1. Install

```bash
pipx install "git+ssh://git@github.com/gutnikov/orca.git"
```

Verify it works:

```bash
orca -v
```

Update to latest:

```bash
pipx install --force "git+ssh://git@github.com/gutnikov/orca.git"
```

> **Prerequisites:** Git, tmux, and at least one AI agent CLI — [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`) or [OpenCode](https://github.com/opencode-ai/opencode) (`opencode`) — must be installed and authenticated.

### 2. Create a Hello World Workflow

Navigate to any git repo and set up the Orca directory structure:

```bash
cd your-repo

# Create the workflow config directory with a prompts subdirectory
mkdir -p .orca/prompts
```

Create the workflow config — a single state that implements whatever the task describes:

```yaml
# .orca/default.yml

issue:
  fields:
    title:
      type: string
      description: "What to build"
    description:
      type: string
      description: "Detailed requirements"

initial: implementing

states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implement.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [done, retry]
          description: "Whether the implementation is complete"
          values_description:
            done: "All changes committed, tests pass"
            retry: "Something went wrong, try again"
        summary:
          type: string
          description: "What was done or what went wrong"
    on:
      done: done
      retry: implementing
```

Create the prompt template:

```markdown
<!-- .orca/prompts/implement.md -->

# Implementing Agent

You are an implementation agent working in an isolated git worktree.

## Task

**{{ issue.fields.title }}**

{{ issue.fields.description }}

## Instructions

1. Read and understand the requirements above
2. Implement the changes
3. Run any existing tests to make sure nothing is broken
4. Commit your changes with a descriptive message

## Output

When finished, write your result to `{{ result_path }}`:

\`\`\`json
{{ result_format | tojson(indent=2) }}
\`\`\`
```

Create a task file:

```yaml
# task.md
---
title: Add a hello endpoint
description: |
  Create a file called hello.py with a function greet(name)
  that returns "Hello, {name}!". Include a test in test_hello.py.
---
```

### 3. Start the Daemon and Run

Orca uses a background daemon to manage runs. Start it, then submit your task:

```bash
# Start the daemon (runs in background)
orca daemon start

# Submit the task
orca run task.md
```

The daemon picks up the task, creates a worktree, spawns an agent, and drives the state machine. You'll see output like:

```
Run started: main:default
```

The run ID format is `branch:workflow` — here it's branch `main` with the `default` workflow.

### 4. Watch It Work in the TUI

Open the live terminal dashboard:

```bash
orca tui
```

The TUI shows:

- **Left panel** — issue tree with state labels and progress bars
- **Right panel** — live terminal output from the active worker, issue details, or session history
- **Header bar** — branch name, active worker count, failure count, elapsed time

Navigate with `j`/`k` (up/down), `h`/`l` (left panel/right panel), and `q` to quit. Press `n` to retry a failed issue.

The TUI connects to the daemon — you can close and reopen it anytime without interrupting the run.

### 5. Monitor and Manage from the CLI

While the TUI is great for watching, the CLI is useful for quick checks and scripting:

```bash
# List all runs
orca runs

# Check worker logs (shows all issues for the run)
orca logs main:default

# Check worker logs for a specific issue (get issue_id from orca runs, state.json, or MCP)
orca logs main:default abc123

# Retry a failed issue
orca retry main:default abc123

# Stop a run
orca stop main:default

# Resume a stopped or failed run
orca resume main:default

# Delete a run and its state
orca drop main:default
```

### 6. Set Up MCP for Your Coding Agent

Add Orca as an MCP server so your coding agent can start, monitor, and control runs directly.

**Claude Code** — add to `.mcp.json` (or `~/.claude/settings.json` for global access):

```json
{
  "mcpServers": {
    "orca": {
      "command": "orca",
      "args": ["mcp"]
    }
  }
}
```

**Cursor** — add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "orca": {
      "command": "orca",
      "args": ["mcp"]
    }
  }
}
```

**VS Code (Copilot)** — add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "orca": {
      "command": "orca",
      "args": ["mcp"]
    }
  }
}
```

Any MCP client that supports stdio transport can use `orca mcp` as the command. See the [MCP Integration](#mcp-integration) section for the full tool reference.

---

## How It Works

A YAML config defines states. Each state has a worker (an AI agent) and transition rules. Workers do their job, return a result, and the result determines the next state. That's it.

### The Core Loop

When you run `orca run task.md`, the following happens:

1. The task file is parsed into an **issue** — a unit of work with fields like title and description.
2. The issue is placed in its **initial state** (defined in your config).
3. If that state has a **worker**, an AI agent is spawned in an isolated **git worktree**.
4. The agent does its work and writes a **result file** (`result.json`) with an **outcome**.
5. The outcome is matched against the state's **transition rules** (`on:`), which determine the next state.
6. Steps 3-5 repeat until the issue reaches the terminal state `done`.

```
                    ┌─────────────────────────────────┐
                    │         Orchestrator Loop        │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │  Pick issue from current state   │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │  Dispatch worker (AI agent)      │
                    │  in isolated tmux + worktree     │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │  Worker writes result.json       │
                    │  { "outcome": "ready", ... }     │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │  Engine reduces event:            │
                    │  outcome → on: rule → next state  │
                    └──────────────┬──────────────────┘
                                   │
                          ┌────────┴────────┐
                          │                 │
                   reached "done"    new state has worker
                          │                 │
                        (stop)        (loop back to top)
```

This loop runs concurrently for all active issues in the run. Multiple agents can work in parallel across different issues and states.

### Issues

An **issue** is the fundamental unit of work. Every run starts with a single root issue created from the task file. Issues carry:

- **Fields** — structured data defined by the workflow config (title, description, scope_boundary, etc.). Workers read these; results can write back to them.
- **State** — the current position in the state machine (e.g., `scoping`, `implementing`, `done`).
- **Event log** — a complete history of everything that happened to this issue: creation, dispatches, results, transitions, failures.
- **Visit counts** — how many times the issue has entered each state (useful for detecting loops).
- **Hop count** — total state transitions so far, bounded by `max_hops`.
- **Failure count** — consecutive worker crashes in the current state, bounded by `max_worker_retries`.

Issues can have **parent-child relationships** (via decomposition) and **dependency edges** (one issue waiting on another).

### States

A **state** represents a phase of work. There are three kinds:

**Active states** have a `worker` and `on` rules. When an issue enters an active state, the orchestrator spawns an AI agent to handle it. The agent's result outcome determines what happens next.

```yaml
implementing:
  worker:
    kind: claude-code
    prompt: prompts/implementing.md
    result_format:
      outcome:
        type: enum
        values: [done, blocked]
  on:
    done: applying
    blocked: planning
```

**Passive states** have no `worker`. Issues can be moved into passive states programmatically (via `AdvanceEvent`) but no agent is dispatched. Useful for wait states or manual gates.

**Terminal states** are the built-in `done` and `failed`. You never define these — they exist automatically. `done` means the issue completed successfully. `failed` triggers retry logic: if a transition targets `failed`, the engine increments the failure counter and re-dispatches the worker (up to `max_worker_retries`).

### Workers

A **worker** is a CLI coding agent that runs inside a tmux session with its own git worktree. Orca ships with built-in support for Claude Code and OpenCode, but the worker protocol works with any CLI agent that can read a prompt and write a JSON result file. Workers are:

- **Isolated** — each worker gets its own copy of the repo via `git worktree`. Workers can commit, branch, and edit files without interfering with each other.
- **Prompted** — the worker receives a Jinja2-rendered prompt with issue context, the expected result schema, and the path to write `result.json`.
- **Validated** — the orchestrator polls for `result.json`, validates it against the `result_format` schema, and sends correction messages if the output is malformed.
- **Supervised** — workers have timeouts (hard and inactivity-based), retry logic with exponential backoff, and progress reporting.

The worker lifecycle:

```
spawn tmux session
    │
    ▼
create git worktree (if needed)
    │
    ▼
render prompt template with issue context
    │
    ▼
start CLI agent (claude / opencode) with prompt
    │
    ▼
poll for result.json ◄──── invalid? send correction message
    │
    ▼
validate result against result_format
    │
    ▼
capture final scrollback to log file
    │
    ▼
kill tmux session, return result to engine
```

If the worker crashes or times out, a `WorkerFailedEvent` is emitted. The engine increments the issue's failure count and re-dispatches (with exponential backoff: 5s, 10s, 20s, 40s...) until `max_worker_retries` is exhausted.

### Transitions

**Transitions** connect states. When a worker returns a result, the `outcome` value is looked up in the state's `on:` rules:

```yaml
on:
  ready: implementing      # simple: move to "implementing"
  needs_rescope: scoping   # loop back: re-enter "scoping"
  done: done               # terminal: issue is complete
  failed: failed           # retry: increment failure count, re-dispatch
```

Transitions can also loop — `blocked: planning` sends the issue back to a previous state. The engine tracks `visit_counts` per state, so prompt templates can detect retries and include previous failure context.

Transitions targeting `failed` are special: instead of moving the issue to a terminal state, they trigger the same retry machinery as a worker crash. The worker's `reason` field is stored in `failure_context` and the issue stays in its current state for re-dispatch.

### The Engine (Reducer)

The engine is a **pure, deterministic state machine**. It follows the reducer pattern:

```
reduce(config, state, event) → (new_state, effects)
```

- **State** is the complete snapshot of all issues, their fields, states, event logs, and worker queues.
- **Events** are things that happened: `CreateEvent`, `WorkerResultEvent`, `WorkerFailedEvent`, `WorkerWaitingEvent`, `WorkerResumedEvent`, `AdvanceEvent`.
- **Effects** are commands to execute: `DispatchWorkerEffect` (spawn a worker) and `ErrorEffect` (log an error).

The engine never performs side effects itself. It deep-copies state before mutation, processes the event, and returns a new state plus a list of effects. The orchestrator interprets those effects — spawning workers, writing to disk, creating worktrees. This separation makes the engine fully testable in isolation without any I/O.

### Decomposition

**Decomposition** is how a single large issue becomes many smaller ones. When a worker returns `outcome: decompose`, the engine:

1. Reads the `sub_issues` list from the result.
2. Creates a child issue for each entry, with its own fields, state, and event log.
3. Resolves `depends_on` references between siblings into real issue IDs.
4. Dispatches non-blocked children to their initial states.
5. Optionally transitions the parent to a `then` state (usually `done`).

```
            ┌─────────────────────┐
            │    Root Issue       │
            │  [scoping] → done   │
            └────────┬────────────┘
                     │ decompose
          ┌──────────┼──────────┐
          ▼          ▼          ▼
     ┌─────────┐ ┌─────────┐ ┌─────────┐
     │ database │ │   api   │ │  tests  │
     │ [plan…] │ │ (waits) │ │ (waits) │
     └─────────┘ └─────────┘ └─────────┘
                  depends_on:  depends_on:
                  [database]   [database, api]
```

Children flow through the state machine independently and in parallel (respecting `depends_on` edges and `max_workers` limits). When a child reaches `done`, the engine runs **cascading unblock**:

- **Decomposition unblock** — if all siblings of the completed child are `done`, the parent issue is unblocked and either transitions (if `then` was specified) or gets re-dispatched in its current state.
- **Dependency unblock** — any issue listing the completed child in its `depends_on` is checked. If all dependencies are now `done` and the issue isn't otherwise blocked, it gets dispatched.

### Concurrency Control

Multiple issues can have active workers simultaneously. The engine provides two mechanisms to control concurrency:

**`max_workers` per state** — caps how many issues in a given (type, state) pair can have active workers at once. Excess issues are placed in a FIFO queue. When a worker completes and frees a slot, the next non-blocked issue in the queue is dispatched. This is how you serialize operations:

```yaml
applying:
  max_workers: 1    # only one merge at a time
```

**`depends_on` between issues** — blocks an issue until all its dependencies reach `done`. The engine checks this at dispatch time and again via cascading unblock when dependencies complete.

### Persistence and Crash Recovery

The orchestrator persists state to disk after every reducer call:

```
.orca-state/runs/{branch}/{workflow}/
  state.json            # full state snapshot (all issues)
  branches.json         # issue-to-branch mapping
  sessions.json         # worker session manifest
  orca.log.jsonl        # structured event log
  config_source.json    # path to the config file used
```

If the daemon crashes or is stopped, the next startup scans `.orca-state/runs/` for non-terminal runs, marks in-flight workers as failed, and makes the run available for resume. `orca resume <run_id>` rebuilds the orchestrator from the persisted state, recovers any valid `result.json` files written by workers before the crash, and re-dispatches incomplete issues.

### Worktrees

Each issue gets its own **git worktree** — a separate checkout of the repo on its own branch. This means:

- Workers can commit freely without conflicting with each other.
- Each issue's branch is derived from its parent's branch (for children) or the root branch.
- Branch names are auto-generated from issue titles: `feature-auth-database-models`, `feature-auth-api-endpoints`, etc.
- The `applying` state typically handles merging the worktree branch back to the integration branch.

Worktrees live under `.orca-state/worktrees/` and are managed by `WorktreeManager`.

### Event Flow Summary

Here's the complete event flow for a run with decomposition:

```
1. CreateEvent(root_issue)
   → root issue created in initial state
   → DispatchWorkerEffect (scoping agent)

2. WorkerResultEvent(outcome: "decompose", sub_issues: [...])
   → child issues created with depends_on edges
   → parent transitions to "done" (via then:)
   → DispatchWorkerEffect for each non-blocked child

3. WorkerResultEvent(child_1, outcome: "ready")
   → child_1 transitions: planning → implementing
   → DispatchWorkerEffect (implementing agent)
   → cascading unblock: child_2 was waiting on child_1, now dispatched

4. WorkerFailedEvent(child_2)
   → failure_count incremented (1 of 3)
   → DispatchWorkerEffect (retry with 5s backoff)

5. WorkerResultEvent(child_2, outcome: "done")
   → child_2 transitions to done
   → cascading unblock: child_3 was waiting on child_1 + child_2

6. WorkerResultEvent(child_1, outcome: "done")
   → all children done → parent confirmed terminal
   → run complete
```

---

## Configuration

Orca workflows are defined in YAML files inside a `.orca/` directory at your repository root. A workflow file describes a state machine: what states an issue moves through, which AI agent handles each state, what results are expected, and how outcomes route to the next state.

### File Layout

```
your-repo/
  .orca/
    default.yml          # used when no -w flag is given
    develop.yml          # orca run task.md -w develop
    hotfix.yml           # orca run task.md -w hotfix
    prompts/
      scoping.md         # Jinja2 prompt templates
      planning.md
      implementing.md
  task.md                # issue description
```

Orca resolves the config file using this priority:

1. **Explicit path** — if `-w` contains `/` or ends with `.yml`, it's treated as a file path (absolute, relative, or `~`-prefixed).
2. **Shorthand name** — `-w develop` resolves to `.orca/develop.yml`.
3. **Default** — no `-w` flag resolves to `.orca/default.yml`.

The directory containing the config file becomes the **flow root** — all relative prompt paths resolve from there.

### Minimal Example

The simplest possible workflow — one state, one worker, two outcomes:

```yaml
# .orca/default.yml

issue:
  fields:
    title:
      type: string
      description: "Issue title"
    description:
      type: string
      description: "What needs to be done"

initial: implementing

states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [done, blocked]
          description: "Implementation result"
    on:
      done: done
      blocked: implementing    # retry
```

### Full Example

A 5-stage pipeline with decomposition, dependency tracking, serialized merges, and a retrospective. See [`examples/project/orca.yml`](examples/project/orca.yml) for the complete annotated file.

```
scoping -> planning -> implementing -> applying -> retro -> done
     \                      |
      <- needs_rescope -----+
```

```yaml
# .orca/default.yml

base_branch: origin/main

issue:
  fields:
    title:
      type: string
      description: "Short title for the issue"
    description:
      type: string
      description: "Detailed description of what needs to be done"
    scope_boundary:
      type: string
      description: "Files and directories this issue owns"

initial: scoping

states:
  scoping:
    worker:
      kind: claude-code
      prompt: prompts/scoping.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [decompose, ready]
          values_description:
            decompose: "Break into isolated sub-issues"
            ready: "Small enough for a single worker"
        sub_issues:
          type: list
          items: "$issue"
          required_when: [decompose]
    on:
      decompose:
        action: decompose
        then: done
      ready: planning

  planning:
    worker:
      kind: claude-code
      prompt: prompts/planning.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [ready, needs_rescope]
        summary:
          type: string
          description: "Brief summary of the plan"
    on:
      ready: implementing
      needs_rescope: scoping

  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      timeout: 3600
      result_format:
        outcome:
          type: enum
          values: [done, blocked]
        summary:
          type: string
          description: "What was implemented or what's blocking"
    on:
      done: applying
      blocked: planning

  applying:
    max_workers: 1           # serialize merges
    worker:
      kind: claude-code
      prompt: prompts/applying.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [applied, failed]
        summary:
          type: string
    on:
      applied: retro
      failed: implementing

  retro:
    worker:
      kind: claude-code
      prompt: prompts/retro.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [done]
    on:
      done: done
```

---

### Config Reference

#### Top-Level Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `base_branch` | string | `origin/main` | Git ref to branch from when using `-b` mode. Overridden by `--base` CLI flag. |
| `initial` | string | *required* | The state every new issue starts in. Must reference an existing state. |
| `issue` | mapping | — | Schema for issue data. Contains `fields`. |
| `states` | mapping | *required* | All states in the workflow. |

For multi-type workflows, replace `initial`/`issue`/`states` with `root_type` and `types`. See [Multi-Type Workflows](#multi-type-workflows) below.

#### Issue Fields

```yaml
issue:
  fields:
    title:
      type: string
      description: "Short title"
    priority:
      type: string
      description: "Priority level"
```

Fields are the data each issue carries. Workers access them via `{{ issue.fields.title }}` in Jinja2 prompt templates. The `type` is informational (not enforced at runtime). Task files populate these fields.

#### States

Each state defines an optional worker and transition rules:

```yaml
states:
  reviewing:
    max_workers: 2              # optional: cap concurrent workers in this state
    worker:
      kind: claude-code
      prompt: prompts/review.md
      # ... (see Worker below)
    on:
      approved: done
      rejected: implementing
```

States without a `worker` are passive — no agent is dispatched. The built-in states `done` and `failed` must not be defined explicitly.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `worker` | mapping | — | Worker definition. States without this are passive. |
| `on` | mapping | — | Outcome-to-transition rules. |
| `max_workers` | int | unlimited | Max concurrent workers for this (type, state) pair. Excess issues are queued FIFO. |

#### Worker

The `worker` block defines which AI agent runs and how:

```yaml
worker:
  kind: claude-code              # required: see Worker kinds table below
  prompt: prompts/implement.md   # required: Jinja2 template path (relative to .orca/ directory)
  timeout: 3600                  # optional: hard timeout in seconds
  inactivity_timeout: 300        # optional: kill if no result.json within N seconds
  model: claude-sonnet-4-20250514           # optional: model override
  args: ["--max-turns", "100"]   # optional: extra CLI args
  progress: true                 # optional: inject progress reporting (default: false)
  result_format:                 # required for active states
    # ...
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `kind` | string | *required* | `"claude-code"` or `"opencode"`. |
| `prompt` | string | *required* | Path to Jinja2 template, relative to the `.orca/` directory (the directory containing the `.yml` file). |
| `timeout` | int | none | Hard timeout in seconds. Worker is killed after this duration. |
| `inactivity_timeout` | int | 300 | Seconds without a valid `result.json` before the worker is killed. |
| `model` | string | none | Override the AI model (passed to the CLI agent). |
| `args` | list | none | Extra CLI arguments appended to the worker command. |
| `progress` | bool | `false` | When `true`, workers emit `PROGRESS: <percent> \| <status>` lines shown in the TUI. |
| `result_format` | mapping | *required** | JSON schema the worker must write to `result.json`. *Required for active states (states with both `worker` and `on`). |

**Worker kinds:**

| Kind | Binary | Prompt delivery | Default args |
|------|--------|-----------------|--------------|
| `claude-code` | `claude` | stdin | `--dangerously-skip-permissions --max-turns 50` |
| `opencode` | `opencode` | CLI argument | `run` |

#### Result Format

The `result_format` defines the JSON schema workers must produce. Three field types are supported:

**`enum`** — a fixed set of string values. Every active state must have an `outcome` field of this type.

```yaml
outcome:
  type: enum
  values: [done, blocked, needs_rescope]
  description: "What the worker decided"
  values_description:              # optional: explain each value
    done: "All tests pass, changes committed"
    blocked: "Cannot proceed, explain in summary"
    needs_rescope: "Issue too large, needs decomposition"
```

**`string`** — a free-text field.

```yaml
summary:
  type: string
  description: "Brief summary of what happened"
  required_when: [blocked]         # optional: required only for certain outcomes
```

**`list`** — a list field. Use `items: "$issue"` for decomposition sub-issues.

```yaml
sub_issues:
  type: list
  items: "$issue"                  # each item follows the issue field schema
  description: "Child issues to create"
  required_when: [decompose]
```

#### Transitions (`on`)

Each key in `on:` maps a result `outcome` value to a transition:

**Simple transition** — move to another state:

```yaml
on:
  done: applying           # move to "applying"
  blocked: planning         # loop back to "planning"
  failed: failed            # built-in terminal state
```

**Decomposition** — create child issues from the worker's `sub_issues` list:

```yaml
on:
  decompose:
    action: decompose
    child_type: task        # optional: type for children (defaults to same type)
    then: done              # optional: state parent moves to after decomposition
```

Targets must be existing states or the built-in states `done` and `failed`.

#### Built-in States

Two states exist automatically — do not define them in `states:`:

- **`done`** — terminal success. When an issue reaches `done`, its parent and dependent issues are checked for unblocking.
- **`failed`** — terminal failure. Triggers retry semantics governed by `max_worker_retries`.

#### Built-in Outcome: `waiting`

Any worker can write `{"outcome": "waiting", "reason": "..."}` to its result file to pause its session. This is a built-in outcome — it does not need to be declared in `result_format` or `on:`.

When a worker writes `waiting`:
- The tmux session stays alive (full conversation context preserved)
- The inactivity timer pauses
- The worker waits for an explicit unblock command

```bash
orca unblock <run_id> <issue_id> -m "PR merged, continue"
```

The message is injected into the live session and execution resumes. Workers can block and unblock multiple times.

---

### Task Files

Task files define the initial issue fields. Passed as the first CLI argument.

**YAML format** (recommended):

```yaml
---
title: Build a REST API for task management
description: |
  Create a task management API with lists, tasks, ordering, and CRUD endpoints.
scope_boundary: src/api/
---
```

**Plain text format** (legacy):

```
Build a REST API for task management
Create a task management API with lists, tasks, ordering, and CRUD endpoints.
```

First line becomes `title`, remainder becomes `description`.

See [`examples/project/task.md`](examples/project/task.md) for a full example.

---

### Decomposition and Dependencies

When a worker returns `outcome: decompose`, Orca creates child issues from the `sub_issues` list. Each sub-issue gets its own worktree and flows through the state machine independently.

Workers specify dependencies between children using `depends_on` — a list of `key` values referencing sibling issues. Dependent issues wait until all their dependencies reach `done` before dispatching.

```json
{
  "outcome": "decompose",
  "sub_issues": [
    {
      "key": "database",
      "fields": { "title": "Database models", "scope_boundary": "src/models/" }
    },
    {
      "key": "api",
      "fields": { "title": "API endpoints", "scope_boundary": "src/routes/" },
      "depends_on": ["database"]
    },
    {
      "key": "tests",
      "fields": { "title": "Integration tests", "scope_boundary": "tests/" },
      "depends_on": ["database", "api"]
    }
  ]
}
```

This creates a DAG: `database` runs first, `api` starts when `database` is done, `tests` starts when both are done.

---

### Multi-Type Workflows

For workflows where parent and child issues follow different state machines, use the multi-type format:

```yaml
root_type: epic

types:
  epic:
    fields:
      title: { type: string, description: "Epic title" }
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scope-epic.md
          result_format:
            outcome:
              type: enum
              values: [decompose]
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
        on:
          decompose:
            action: decompose
            child_type: task        # children use the "task" type
            then: done

  task:
    fields:
      title: { type: string, description: "Task title" }
      scope_boundary: { type: string, description: "Owned files" }
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/implement-task.md
          result_format:
            outcome:
              type: enum
              values: [done, blocked]
            summary:
              type: string
        on:
          done: done
          blocked: implementing
```

The single-type format (`issue`/`states`/`initial` at the top level) is syntactic sugar — internally it becomes a multi-type config with one type called `"default"`.

---

### Prompts

Prompts are Jinja2 markdown templates. The following variables are available:

| Variable | Description |
|----------|-------------|
| `{{ issue.fields.* }}` | Issue field values (e.g., `title`, `description`, `scope_boundary`) |
| `{{ issue.event_log }}` | List of state transition events for this issue |
| `{{ issue.children }}` | Child issues from a previous decomposition attempt |
| `{{ issue.depends_on }}` | IDs of issues this one depends on |
| `{{ issue.decomposed_from }}` | Parent issue ID (if this is a child issue) |
| `{{ result_format \| tojson(indent=2) }}` | The output JSON schema the worker must produce |
| `{{ result_path }}` | Path where the worker writes `result.json` |
| `{{ run }}` | Run context — session logs, insights, state paths, summary (see below) |

The `run` variable is available in all prompts and contains:

| `run.*` | Description |
|---------|-------------|
| `run.branch` | Git branch name |
| `run.workflow` | Workflow name |
| `run.sessions` | List of worker sessions with `state`, `log`, `duration`, `outcome` |
| `run.summary.states_visited` | States the run has passed through |
| `run.summary.total_duration` | Total elapsed time |
| `run.summary.outcomes` | Map of state -> outcome for each completed phase |
| `run.summary.failures` | Map of state -> error for any failures |
| `run.log` | Path to the structured event log (JSONL) |
| `run.insights` | Path to insights file (JSON), if insights are enabled |
| `run.state` | Path to the state snapshot (JSON) |

Orca automatically appends a result-file warning to every rendered prompt. The [One-Prompt Setup](#one-prompt-setup) copies workflow reference docs into `.orca/reference/` in your project — these include a [prompt guide](prompts/create-orca-workflow/prompt-guide.md) (writing principles, pitfalls, template anatomy), [config reference](prompts/create-orca-workflow/config-reference.md), and [audit checklist](prompts/create-orca-workflow/audit-checklist.md). When creating or modifying workflows, tell your coding agent: *"Read `.orca/reference/` and then update my workflow."*

See [`examples/project/prompts/`](examples/project/prompts/) for complete prompt templates.

---

### CLI Reference

```
orca daemon start              # start the background daemon
orca daemon stop               # stop the daemon
orca daemon status             # check daemon status

orca run <task.md> [options]   # start a run
orca runs                     # list all runs
orca stop <run_id>            # stop a run
orca resume <run_id>          # resume a stopped/failed run
orca drop <run_id>            # stop + delete run state
orca retry <run_id> <issue_id>  # retry a failed issue
orca clean [--dry-run] [-y]   # drop terminal runs + clean accumulated artifacts

orca logs <run_id> [issue_id] [--tail N]        # view worker logs
orca unblock <run_id> <issue_id> -m "message"   # unblock a waiting worker
orca tui                      # open TUI dashboard
orca mcp                      # start MCP stdio bridge
```

**`orca run` options:**

| Flag | Default | Description |
|------|---------|-------------|
| `-w WORKFLOW` | `default` | Workflow name or path. `-w develop` loads `.orca/develop.yml`. |
| `-b BRANCH` | current branch | Integration branch name. Enables concurrent run isolation. |
| `--base REF` | config `base_branch` | Git ref to branch from. Requires `-b`. |
| `--headless` | off | Run without TUI. |
| `--insights` | off | Enable insights agent for progress monitoring. |
| `--max-hops N` | `10` | Max state transitions per issue before stopping. |
| `--max-retries N` | `3` | Max worker crash retries per issue before giving up. |

---

### MCP Integration

Orca exposes its full daemon API as [MCP](https://modelcontextprotocol.io/) tools, allowing AI agents like Claude Code, Cursor, Windsurf, or any MCP-compatible client to start, monitor, and control workflow runs programmatically.

#### How It Works

The MCP server runs as a **stdio bridge** — the client spawns `orca mcp` as a subprocess and communicates over stdin/stdout. The MCP server proxies every call to the orca daemon's HTTP API over its Unix socket. This means the daemon must be running for the tools to work.

```
┌──────────────┐     stdio      ┌──────────────┐    Unix socket    ┌──────────────┐
│  MCP Client  │ ◄────────────► │   orca mcp   │ ◄───────────────► │  orca daemon │
│ (Claude Code │                │  (FastMCP)   │                   │  (Uvicorn)   │
│  Cursor etc) │                └──────────────┘                   └──────────────┘
└──────────────┘
```

#### Setup

**1. Start the daemon** in the repo you want to manage:

```bash
cd your-repo
orca daemon start
```

**2. Add the MCP server** to your client's configuration.

**Claude Code** — add to `~/.claude/settings.json` or your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "orca": {
      "command": "orca",
      "args": ["mcp"]
    }
  }
}
```

**Cursor** — add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "orca": {
      "command": "orca",
      "args": ["mcp"]
    }
  }
}
```

**VS Code (Copilot)** — add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "orca": {
      "command": "orca",
      "args": ["mcp"]
    }
  }
}
```

**Other MCP clients** — any client that supports stdio transport can use `orca mcp` as the command.

> **Note:** If `orca` is not on your PATH (e.g., installed via `pipx`), use the full path to the binary. Find it with `which orca`.

**3. Use it.** Every tool takes a `root` parameter — the absolute path to the repo root where the daemon is running. The MCP server resolves the correct daemon socket from this path automatically.

#### Available Tools

All tools require `root` (absolute path to the repo) as the first parameter.

**Run lifecycle:**

| Tool | Parameters | Description |
|------|-----------|-------------|
| `orca_start_run` | `root`, `task_file`, `workflow?`, `branch?`, `run_id?` | Start a new workflow run. `task_file` is the path to the task markdown file. |
| `orca_stop_run` | `root`, `run_id` | Stop a running workflow. Kills all active workers. |
| `orca_resume_run` | `root`, `run_id` | Resume a stopped, failed, or interrupted run. |
| `orca_drop_run` | `root`, `run_id` | Stop and delete all persisted state for a run. |

**Monitoring:**

| Tool | Parameters | Description |
|------|-----------|-------------|
| `orca_daemon_status` | `root` | Daemon uptime, active run count, total run count. |
| `orca_list_runs` | `root` | List all runs with status, branch, workflow, issue counts. |
| `orca_get_run` | `root`, `run_id`, `compact?` | Full run state with all issues and sessions. Use `compact: true` for lightweight polling (strips event logs and completed sessions). |
| `orca_get_issue` | `root`, `run_id`, `issue_id` | Full details for a single issue: fields, state, event log. |
| `orca_get_worker_log` | `root`, `run_id`, `issue_id`, `tail?` | Terminal output from the latest worker session for an issue. `tail` defaults to 100 lines. |
| `orca_get_insights` | `root`, `run_id` | Insights agent output (if `--insights` was enabled). |

**Intervention:**

| Tool | Parameters | Description |
|------|-----------|-------------|
| `orca_retry_issue` | `root`, `run_id`, `issue_id` | Retry a failed issue. Resets failure count and re-dispatches. Restarts the run if it had stopped. |
| `orca_unblock_worker` | `root`, `run_id`, `issue_id`, `message` | Unblock a waiting worker. The `message` is injected into the live tmux session. |

#### Run IDs

Run IDs follow the format `branch:workflow` (e.g., `main:default`, `feature-auth:develop`). You can find them via `orca_list_runs` or by constructing them from the branch and workflow name.

#### Example Usage

A typical agent interaction with Orca via MCP:

```
Agent: "Start a workflow run for this task"
→ orca_start_run(root="/path/to/repo", task_file="task.md")
← {"run_id": "main:default"}

Agent: "How's it going?"
→ orca_get_run(root="/path/to/repo", run_id="main:default", compact=true)
← {"run_id": "main:default", "status": "running", "issues": {...}, "sessions": {...}}

Agent: "Show me what the implementing worker is doing"
→ orca_get_worker_log(root="/path/to/repo", run_id="main:default", issue_id="abc-123", tail=50)
← (terminal output)

Agent: "That issue failed, retry it"
→ orca_retry_issue(root="/path/to/repo", run_id="main:default", issue_id="abc-123")
← {"status": "retry requested"}

Agent: "The worker is waiting for a PR merge"
→ orca_unblock_worker(root="/path/to/repo", run_id="main:default", issue_id="abc-123",
                      message="PR #42 merged, continue with integration")
← {"status": "ok"}
```

---

### Validation Rules

The config parser validates on load. These are the most common errors and what they mean:

| Rule | Error message |
|------|---------------|
| Root type must exist | `root_type 'X' does not exist in types` |
| Initial state must exist | `initial state 'X' does not exist in states` |
| `done`/`failed` are reserved | `states ['done'] are built-in and must not be defined explicitly` |
| Worker kind must be valid | `kind must be one of ['claude-code', 'opencode']` |
| Worker prompt must be non-empty | `worker prompt for state 'X' must be a non-empty string` |
| Active states need outcome enum | `active state 'X' must have 'outcome' of type enum in result_format` |
| `on` keys must match outcomes | `on key 'Y' in state 'X' does not match any outcome value` |
| States must be able to progress | `state 'X' has no outcome values with matching on: rules` |
| Transition targets must exist | `on.Y target 'Z' in state 'X' does not exist in states` |
| Decompose needs sub_issues | `state 'X' has action: decompose but result_format is missing 'sub_issues'` |
| States must be reachable | `state 'X' is not reachable from any on rule` |
| `max_workers` must be positive | `max_workers for state 'X' must be a positive integer` |
| `timeout` must be positive | `worker timeout for state 'X' must be a positive integer` |
| `max_hops` must be positive | `max_hops must be a positive integer` |

---

## Workflow Patterns

Orca workflows are composable — mix and match these patterns to build your pipeline. Full config snippets for each pattern are in `.orca/reference/workflow-patterns.md` (copied during [setup](#one-prompt-setup)) or in the [source repo](prompts/create-orca-workflow/workflow-patterns.md).

### Sequential Pipeline

Issue moves through stages one at a time. Each stage has a fail-safe that loops back.

```
planning → implementing → reviewing → done
    ↑           |              |
    └── blocked ┘   └── needs_rework ──┘
```

### Decompose + Parallel Execution

A scoping agent breaks a large task into sub-issues. Children run in parallel, each in its own worktree. A serialized `applying` state merges them one at a time.

### Serialized Merge

Use `max_workers: 1` on any state where only one worker should run at a time — merging, deploying, writing to a shared resource. Excess issues queue FIFO and dispatch as slots free up.

### Retry Loop with Escalation

`blocked` loops back to the same state, giving the worker another attempt with failure context. `max_worker_retries` bounds the total crash retries. `max_hops` bounds the total state transitions (prevents infinite back-and-forth).

### Iterative Refinement

Implement → review → rework cycle. The reviewing agent produces actionable feedback, the implementing agent reads `{{ issue.event_log }}` to see what went wrong last time.

### Multi-Type Hierarchy

Different issue types with independent state machines. An `epic` decomposes into `story` issues, which decompose into `task` issues. Each type has its own fields, states, and prompts.

### Gate State

A passive state (no `worker`, no `on:` rules) where the issue waits for manual advancement. Use for code review gates, deployment approvals, or manual QA sign-off.

---

## Progress Reporting

Workers can report real-time progress to the TUI by printing progress lines to stdout:

```
PROGRESS: 25 | Exploring codebase structure
PROGRESS: 50 | Writing implementation
PROGRESS: 80 | Running tests
PROGRESS: 100 | All tests passing, committing
```

The format is `PROGRESS: <percent> | <status>` where `<percent>` is 0-100 and `<status>` is a short description. The TUI displays this as a progress bar with status text in the issue tree.

To enable, set `progress: true` on the worker:

```yaml
implementing:
  worker:
    kind: claude-code
    prompt: prompts/implementing.md
    progress: true              # injects progress instructions into the prompt
    result_format:
      # ...
```

When enabled, Orca automatically injects reporting instructions into the rendered prompt. Workers should emit progress lines after meaningful milestones, not on every action.

---

## Concurrent Runs

Run multiple independent workflows in the same repo. Each run gets its own integration branch and isolated worktrees:

```bash
# Start the daemon once
orca daemon start

# Submit multiple tasks on separate branches
orca run task-auth.md -b feature-auth
orca run task-billing.md -b feature-billing
orca run task-search.md -b feature-search --base origin/develop
```

Each run is identified by `branch:workflow` (e.g., `feature-auth:default`). Runs share the daemon but are fully isolated — separate state, separate worktrees, separate workers.

```bash
# Monitor all runs
orca runs

# Stop just one
orca stop feature-auth:default

# Open TUI — shows all active runs
orca tui
```

Set the default base ref in your workflow config:

```yaml
base_branch: origin/main      # branches are created from here
```

Override per-run with `--base`:

```bash
orca run task.md -b hotfix-123 --base origin/release/v2
```

---

## Resume & Crash Recovery

If the daemon crashes, is killed, or the machine restarts, no work is lost. Orca persists state to disk after every state transition.

On the next `orca daemon start`, the daemon scans `.orca-state/runs/` for non-terminal runs and marks them as **interrupted**. You can then resume:

```bash
orca resume main:default
```

What happens on resume:

1. **State is loaded** from the last persisted `state.json`.
2. **Hop counts reset** to 0 on non-terminal issues (prevents re-triggering `max_hops` from a previous session).
3. **Orphan sessions** from the crashed run are marked as completed.
4. **Result recovery** — Orca scans for `result.json` files that workers wrote before the crash. Valid results are fed back into the engine, avoiding re-running completed work.
5. **Failed workers** are re-dispatched with their failure counts preserved, so retry limits continue to apply.

If a run was stopped intentionally with `orca stop`, the same resume flow applies. In-flight workers are marked as failed, and resume re-dispatches them.

---

## The `.orca-state/` Directory

Orca stores all runtime state under `.orca-state/` at the repo root. **You must add it to `.gitignore`** — it contains runtime data, logs, and worktrees that should not be committed.

```
.orca-state/
  runs/
    {branch}/
      {workflow}/
        state.json           # full state snapshot — all issues, fields, event logs
        sessions.json        # worker session manifest — start/end times, log paths, progress
        branches.json        # issue-to-branch mapping
        orca.log.jsonl       # structured event log (one JSON object per line)
        config_source.json   # path to the config file used for this run
        insights.json        # insights agent findings (if --insights enabled)
        retry/               # retry signal files (created by TUI/CLI)
  worktrees/
    {branch-name}/           # git worktree checkouts, one per issue
  sessions/
    {state}-{timestamp}.log  # tmux scrollback capture for each worker session
```

The daemon also stores per-repo state globally:

```
~/.orca-state/
  daemons/
    {repo-hash}/
      daemon.pid             # PID of the running daemon
      daemon.sock            # Unix domain socket
      root                   # repo root path (for reverse lookup)
```

**You can inspect any of these files** for debugging. `state.json` shows the current state of all issues. `sessions.json` shows worker history. The `.log` files contain raw terminal output from each worker session.

**Do not modify these files** while the daemon is running — it will overwrite your changes on the next state transition.

---

## Daemon Management

The daemon is a long-running background process that manages all runs for a repo. One daemon per repo, identified by a SHA-1 hash of the repo root path.

```bash
orca daemon start              # start in background (daemonizes)
orca daemon start --foreground # stay in foreground (useful for debugging)
orca daemon status             # check if running, show PID
orca daemon stop               # graceful shutdown (SIGTERM)
```

**Lifecycle details:**

- On start, the daemon writes a pidfile and Unix socket under `~/.orca-state/daemons/{hash}/`.
- On stop (`orca daemon stop` or SIGTERM), it cancels all in-flight workers, kills tmux sessions, cleans up the pidfile and socket.
- If the daemon crashes, the next `orca daemon start` detects the stale pidfile (checks if the PID is alive), cleans it up, and starts fresh.
- If a stale socket file exists from a previous crash, it's removed automatically on startup.
- The daemon scans `.orca-state/runs/` on startup for interrupted runs and makes them available for `orca resume`.

**Troubleshooting:**

| Problem | Fix |
|---------|-----|
| `Error: daemon is not running` | Run `orca daemon start` |
| `Error: daemon already running` | Run `orca daemon stop` first, or check with `orca daemon status` |
| Daemon won't start after crash | The stale pidfile should auto-clean. If not, delete `~/.orca-state/daemons/*/daemon.pid` manually |
| Socket errors | Delete `~/.orca-state/daemons/*/daemon.sock` and restart the daemon |
| Workers stuck after daemon restart | Run `orca resume <run_id>` — orphan workers are detected and re-dispatched |

---

## Troubleshooting

### Common Failure Modes

**Worker timed out** — no valid `result.json` within the inactivity timeout (default: 5 minutes, or the `inactivity_timeout`/`timeout` value from config). The worker is killed and the issue's failure count increments. Check the worker's session log to see what it was doing.

**Invalid result file** — the worker wrote `result.json` but it doesn't match the `result_format` schema (missing `outcome` field, unknown outcome value, missing required fields). The orchestrator sends a correction message to the worker's live session: *"URGENT: Your result file is INVALID..."* and gives it another chance. If the session has already exited, it's treated as a failure.

**Max retries exhausted** — the worker crashed or timed out `max_worker_retries` times (default: 3) in the same state. The issue stops, and the run may deadlock. Reset the failure count and try again with `orca retry <run_id> <issue_id>`, the TUI `n` key, or the `orca_retry_issue` MCP tool.

**Max hops reached** — the issue transitioned between states `max_hops` times (default: 10). This usually means a loop (e.g., `implementing → planning → implementing` cycling). Check the event log for repeated transitions and fix the workflow or prompts.

**Deadlock** — no workers are in flight and no pending effects. This happens when all issues are either stuck (retries exhausted) or blocked on dependencies that can't complete. The orchestrator logs a warning and stops. Retry the stuck issues.

### Debugging a Failed Run

```bash
# 1. Check run status — note issue IDs in the output
orca runs

# 2. View worker logs for the run (or a specific issue)
orca logs <run_id>
orca logs <run_id> <issue_id>

# 3. Read the structured event log
cat .orca-state/runs/{branch}/{workflow}/orca.log.jsonl | python -m json.tool

# 4. Check the full state (includes all issue IDs and their current states)
cat .orca-state/runs/{branch}/{workflow}/state.json | python -m json.tool

# 5. Retry the failed issue
orca retry <run_id> <issue_id>

# 6. Or resume the entire run
orca resume <run_id>
```

### Log Formats

**`orca.log.jsonl`** — structured event log. Each line is a JSON object:

```json
{"timestamp": "2026-04-15T10:30:00Z", "level": "INFO", "message": "Worker dispatched for issue abc-123 in state implementing", "event": "worker_dispatched", "issue_id": "abc-123", "state": "implementing"}
```

Filter for a specific issue: `grep '"issue_id": "abc-123"' orca.log.jsonl`

**Session logs** (`.log` files) — raw tmux scrollback from each worker session. These are plain text terminal output including ANSI escape sequences. Use `less -R` to read them with colors.

---

## TUI Keyboard Shortcuts

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
