---
name: orca-install
description: Use when the user wants to install, set up, bootstrap, or add Orca to a project. Triggers on "set up orca", "install orca", "bootstrap orca", "add orca to this repo", or any first-time orca onboarding. Handles pipx install, daemon start, .gitignore, .orca scaffolding, and a smoke-test run.
---

# Set up Orca in this project

End-to-end bootstrap: install the CLI, start the daemon, scaffold a starter workflow under `.orca/`, run a test task to confirm everything works.

Follow these steps in order. If any step fails, stop and tell the user what went wrong — do not try to silently work around it.

## 1. Install Orca

Skip if already installed — check with `which orca`. Otherwise:

```bash
pipx install "git+ssh://git@github.com/gutnikov/orca.git"
```

Verify: `orca -v` should print a version hash. If `which orca` doesn't resolve afterwards, `pipx` likely needs `pipx ensurepath` followed by a shell restart — tell the user.

For the full prereq checklist (pipx, git, tmux, an agent CLI, GitHub SSH), see [`orca-install.md`](../../../../src/orca/playbooks/orca-install.md) in the bundled playbooks.

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

If this project was set up via the Codex Orca plugin, the MCP server is already registered automatically — skip to step 5.

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

Then tell the user to restart or reload their MCP-capable client. Verify the orca tools are available by calling `orca_daemon_status` with `root` set to this project's absolute path.

## 5. Set up the `.orca/` directory

```bash
mkdir -p .orca/prompts
```

Playbooks (the reference docs that teach coding agents how to build, audit, and run workflows) are served via the `orca_get_playbook` MCP tool — they're bundled inside the installed orca package, no per-project copy needed. Call `orca_list_playbooks` to see what's available.

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
      kind: codex
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

When you are finished, write a result file to `{{ result_path }}` with this exact shape:

```json
{
  "outcome": "done"
}
```

The `outcome` field must be the literal string `"done"`. Do not copy a schema definition into the file.
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

Manage runs from the CLI (`orca tui`, `orca runs`, `orca logs`) or keep using MCP through your coding agent. Playbooks live inside the installed orca package and are served via the `orca_get_playbook` MCP tool — whenever the workflow needs to evolve, tell your agent to fetch the relevant playbook and make the change.
