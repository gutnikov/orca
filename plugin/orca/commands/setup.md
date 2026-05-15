---
description: Set up Orca in the current project end-to-end (install, daemon, MCP, starter workflow, test run)
---

# Set up Orca in this project

Follow these steps in order. Stop and tell the user if any step fails.

## 1. Install Orca

Skip if already installed — check with `which orca`. Otherwise:

```bash
pipx install "git+ssh://git@github.com/gutnikov/orca.git"
```

Verify: `orca -v` should print a version hash.

## 2. Start the daemon

```bash
orca daemon start
```

Verify: `orca daemon status` should show it running.

## 3. Add `.orca-state/` to `.gitignore`

This is where Orca stores runtime data, logs, and worktrees:

```bash
echo '.orca-state/' >> .gitignore
```

Skip if already present.

## 4. MCP server registration

If this project was set up via the Claude Code Orca plugin, the MCP server is already registered automatically — skip to step 5.

Otherwise, create `.mcp.json` in the project root:

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

Then tell the user to reload MCP servers (e.g. `/mcp` then restart). Verify the orca tools are available by calling `orca_daemon_status` with `root` set to this project's absolute path.

## 5. Set up the `.orca/` directory

```bash
mkdir -p .orca/prompts
orca init
```

`orca init` copies the bundled workflow reference docs into `.orca/reference/` — these teach coding agents how to build and audit workflows.

## 6. Write a starter workflow

Create `.orca/default.yml`:

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

Create `.orca/prompts/implement.md`:

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

## 7. Create a test task and run it

Write `task.md`:

```yaml
---
title: Add a hello endpoint
description: |
  Create a file called hello.py with a function greet(name)
  that returns "Hello, {name}!". Include a test in test_hello.py.
---
```

Then start a run via the MCP server:

```
orca_start_run(root="<absolute path to this repo>", task_file="task.md")
```

Monitor with `orca_get_run`. If anything fails, check `orca_get_worker_log`, fix the workflow or prompts, `orca_drop_run` the failed run, and retry.

## After setup

Manage runs from the CLI (`orca tui`, `orca runs`, `orca logs`) or keep using MCP through your coding agent. The `.orca/reference/` directory stays in the repo — whenever the workflow needs to evolve, tell your agent to read those docs and make the change.
