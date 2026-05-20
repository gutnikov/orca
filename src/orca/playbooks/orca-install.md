# Playbook: Install & Update Orca

Install the `orca` CLI on this machine via pipx, verify it works, and (later) upgrade it to the latest commit on the upstream repo. Both flows share prerequisites and verification — they're combined here so the agent doesn't have to context-switch.

Routing:
- User says "install orca" or `orca` isn't on PATH → [Install](#install).
- User says "update orca" or `orca` is already installed → [Update](#update).
- Unclear → run `command -v orca` and `orca -v`. If both succeed, propose [Update](#update). If `command -v orca` fails, propose [Install](#install).

---

## Install

### Prerequisites — verify before installing

Run these checks. If any fail, stop and tell the user what's missing — do **not** try to install prerequisites silently.

| Check | Command | Pass condition |
|---|---|---|
| `pipx` is installed | `which pipx` | prints a path |
| `pipx` shims are on `PATH` | `case ":$PATH:" in *":$(pipx environment --value PIPX_BIN_DIR):"*) echo ok;; esac` | prints `ok` |
| `git` is installed | `which git` | prints a path |
| `tmux` is installed | `which tmux` | prints a path |
| At least one agent CLI present | `which claude \|\| which codex \|\| which opencode` | prints a path |
| SSH access to GitHub works | `ssh -T git@github.com` | output proves auth (GitHub's successful-auth/no-shell banner is OK even if the command exits 1); `Permission denied` fails |

If `pipx` is missing, suggest `brew install pipx && pipx ensurepath` (macOS) or the platform-appropriate equivalent. Do not run it without confirmation.

If `pipx` is installed but its bin dir isn't on `PATH`, suggest `pipx ensurepath` and a shell restart **before** installing — otherwise `pipx install` succeeds silently but `command -v orca` won't find anything afterwards (the classic "I installed it, why doesn't it run" trap).

### Already installed? Skip to Update.

```bash
command -v orca
orca -v
```

If both succeed, the CLI is installed. Ask the user whether they want to update instead — see the [Update](#update) section below.

### Install

```bash
pipx install "git+ssh://git@github.com/gutnikov/orca.git"
```

Notes:
- The `git+ssh://` form requires the SSH prereq above. If the user lacks SSH access, do not silently fall back to HTTPS — ask whether they're authorized to clone over HTTPS instead.
- pipx isolates orca in its own venv, so it won't collide with project Pythons.

### Verify

```bash
orca -v          # prints version hash
orca --help      # full subcommand list (daemon, run, runs, resume, retry,
                 # stop, drop, logs, unblock, tui, mcp, init, clean, …)
```

If `orca -v` works but `command -v orca` doesn't resolve in a new shell, `pipx ensurepath` may be needed (then restart the shell).

### Bootstrap a project (per-project, optional here)

Installation alone doesn't set up any project. Inside a project that should use orca:

```bash
cd <project>
mkdir -p .orca/prompts
orca daemon start
orca daemon status    # should show running
```

Also make sure runtime state is not committed:

```bash
grep -qxF '.orca-state/' .gitignore
```

If that check fails, offer to add `.orca-state/` to `.gitignore` and wait for confirmation before editing. This is project policy, not part of installing the binary.

Playbooks no longer need to be copied into the project. Since v0.3.5 they ship with the installed orca package and are served on demand via the `orca_get_playbook` and `orca_list_playbooks` MCP tools. (If you find a legacy `.orca/playbooks/` directory left over from an older orca, `orca init` will remove it — but is otherwise a no-op.)

If the user is not in an orca-enabled project yet, skip this — direct them to [orca-workflow-create.md](orca-workflow-create.md). With the orca plugin installed, the `orca-install` skill auto-triggers on phrases like *"set up orca"* and runs the same end-to-end setup; in environments without the plugin, follow the playbook by reading it directly.

### Done

Report to the user:
- orca version installed
- whether the daemon was started (and where, if so)
- next step: set up a project (invoke the `orca-install` skill if the orca plugin is installed, otherwise follow [orca-workflow-create.md](orca-workflow-create.md)), or run an existing workflow ([orca-workflow-run.md](orca-workflow-run.md))

---

## Update

Upgrade the `orca` CLI to the latest commit on `main` of the upstream repo.

### Pre-flight checks

1. Confirm orca is installed via pipx:
   ```bash
   pipx list | grep -i orca
   ```
   If orca isn't listed but `command -v orca` resolves, it was installed by some other means (system pip, brew, source). **Stop and ask the user** — `pipx install --force` would clobber a non-pipx install.

2. Capture the current version (for the report at the end):
   ```bash
   orca -v
   ```

3. Check for active runs in known Orca project roots the user cares about — there is no global "all projects" registry. Updating restarts each daemon on next invocation. Ask the user before proceeding if any checked project has a `RUNNING` run:
   ```bash
   # in each orca project:
   orca runs
   ```

   Restarting the daemon mid-run is recoverable (orca will mark the run `INTERRUPTED` and `orca resume` can pick it back up), but the user should know.

### Stop any running daemons

For every project that has a running orca daemon, ask the user to stop active runs cleanly first if they care about the live state. Then:

```bash
# in each project that has a daemon:
orca daemon stop
```

The daemon is per-project (one per `.orca/` root) — there's no global daemon to stop.

### Update

```bash
pipx install --force "git+ssh://git@github.com/gutnikov/orca.git"
```

`--force` re-installs into the same venv, picking up the latest commit on `main`. There's no `pipx upgrade` form for git URLs that re-pulls — `--force` is the correct mechanism.

### Verify

```bash
orca -v
orca --help     # confirm subcommand set didn't regress
```

Compare the new version hash to the one captured in pre-flight.

### Restart daemons and resume interrupted runs

For each project that had a running daemon:

```bash
cd <project>
orca daemon start
orca runs
```

For any run shown as `INTERRUPTED`, ask the user before resuming:

```bash
orca resume <run_id>
```

### Reload MCP (if the user is in Claude Code / Cursor / etc.)

If orca is registered as an MCP server in any active editor session, the editor is still holding a handle to the old binary. Tell the user to:
- In Claude Code: `/mcp` → restart the orca server, or reopen the editor.
- In other MCP clients: reload the server connection.

### Done

Report:
- old version → new version
- which projects had their daemons restarted
- any runs that were interrupted/resumed
- reminder to reload MCP in the editor if applicable
