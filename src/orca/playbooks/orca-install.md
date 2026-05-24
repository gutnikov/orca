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

If `pipx` is missing, suggest `brew install pipx` and then `pipx ensurepath` (macOS), or the platform-appropriate equivalent. Do not run installation commands without confirmation.

If `pipx` is installed but its bin dir isn't on `PATH`, suggest `pipx ensurepath` and a shell restart **before** installing — otherwise `pipx install` succeeds silently but `command -v orca` won't find anything afterwards (the classic "I installed it, why doesn't it run" trap).

### Already installed? Skip to Update.

```bash
command -v orca
orca -v
```

If both succeed, the CLI is installed. Ask the user whether they want to update instead — see the [Update](#update) section below.

### Install

**Step 1: Install the CLI**

```bash
pipx install "git+ssh://git@github.com/gutnikov/orca.git"
```

**Step 2: Install the agent plugin**

For Claude Code:
```bash
claude marketplace add gutnikov/orca
claude plugin install orca@orca
```

For Codex:
```bash
codex marketplace add gutnikov/orca
codex plugin install orca@orca
```

Run BOTH if both agents are present on the machine. The plugin provides the orca SKILLs (`orca-install`, `orca-workflow-create`, `orca-workflow-run`, etc.) and the MCP tool wrappers — without it, you can still run orca from the CLI but the agent has no way to invoke it.

After plugin install, **restart the agent** (close and reopen Claude Code / Codex) so the new SKILLs are loaded into the agent's context.

Notes:
- The `git+ssh://` form requires the SSH prereq above. If the user lacks SSH access, do not silently fall back to HTTPS — ask whether they're authorized to clone over HTTPS instead.
- pipx isolates orca in its own venv, so it won't collide with project Pythons.
- Always install CLI + plugin in lockstep. Drift between them causes hard-to-diagnose UX bugs (new fields not surfaced, missing tools, stale SKILL).

### Verify

```bash
orca -v          # prints version hash
orca --help      # full subcommand list (daemon, run, runs, resume, retry,
                 # stop, drop, logs, unblock, tui, mcp, clean, …). `init`
                 # also appears but is a legacy no-op kept only to remove a
                 # stale .orca/playbooks/ directory from very old setups.
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

Upgrade BOTH the `orca` CLI (pipx) AND the orca agent plugins (Claude Code / Codex) to the latest commit on `main`.

**Why both:** orca ships in three loosely-coupled pieces — the pipx CLI/daemon, the Claude Code plugin (SKILLs + MCP tool wrappers), and the Codex plugin equivalent. The pipx CLI updates independently from the plugins; updating only one creates **version skew** that silently degrades behavior (paused-run URLs not surfaced, missing MCP tools, stale SKILL instructions). Always update them together.

### Version-skew check (run this FIRST, every time)

Before doing anything else, check whether CLI and plugins agree:

```bash
# CLI version
orca -v

# Claude Code plugin version (if Claude Code is the active agent)
claude plugin list 2>/dev/null | grep -i orca

# Codex plugin version (if Codex is the active agent)
codex plugin list 2>/dev/null | grep -i orca
```

If versions disagree (e.g. CLI 0.5.4, plugin 0.5.0), report the skew to the user and proceed with the FULL update flow below — even if they only asked to update "orca". A patched CLI without the matching SKILL/MCP plugin will appear to ignore newer fields (`debug_reviews`, `must_surface_to_user`, etc.) and the user will think the feature is broken.

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

3. Check for active runs in known Orca project roots the user cares about — there is no global "all projects" registry. Updating restarts each daemon on next invocation. Ask the user before proceeding if any checked project has a `running` run:
   ```bash
   # in each orca project:
   orca runs
   ```

   Restarting the daemon mid-run is recoverable (orca will mark the run `interrupted` and `orca resume` can pick it back up), but the user should know.

### Stop any running daemons

For every project that has a running orca daemon, ask the user to stop active runs cleanly first if they care about the live state. Then:

```bash
# in each project that has a daemon:
orca daemon stop
```

The daemon is per-project (one per `.orca/` root) — there's no global daemon to stop.

### Update — three steps, in order

**Step 1: Update the CLI / daemon (pipx)**

```bash
pipx install --force "git+ssh://git@github.com/gutnikov/orca.git"
```

`--force` re-installs into the same venv, picking up the latest commit on `main`. There's no `pipx upgrade` form for git URLs that re-pulls — `--force` is the correct mechanism.

**Step 2: Update the agent plugin (Claude Code AND/OR Codex)**

For Claude Code users:
```bash
claude plugin update orca@orca
```

For Codex users:
```bash
codex plugin update orca@orca
```

Run BOTH commands if both agents are installed on the machine — they each have their own plugin cache. Either command is a no-op if the corresponding agent isn't installed; safe to run unconditionally.

> ⚠️ **Claude Code restart required.** The plugin update lands in the cache, but the running Claude Code process holds the old SKILL content in memory. The user must **restart Claude Code** (close and reopen) before the new SKILL is loaded — otherwise the agent will keep using the old SKILL instructions and the update will appear to do nothing. Tell the user this explicitly. Same applies to Codex.

**Step 3: Restart the daemon**

The pipx update replaced the orca binary on disk, but the running daemon is the *old* Python process. To pick up backend changes (new MCP tools, new HTTP fields like `must_surface_to_user`, new playbooks), restart it:

```bash
cd <project>
orca daemon stop && orca daemon start
```

For each project with an active daemon, repeat. Persisted run state is reloaded automatically on restart — paused runs stay paused.

> **Auto-update on daemon start (v0.5.6+)**: `orca daemon start` automatically runs `claude plugin update orca@orca` and `codex plugin update orca@orca` in the background if those CLIs are on PATH. So in practice Step 2 collapses into Step 3 — restart the daemon and the plugins refresh themselves. The user still has to **restart their editor** (Claude Code / Codex) to load the new SKILL into the agent context. Set `ORCA_NO_AUTO_UPDATE=1` in the environment to opt out.

### Verify

```bash
orca -v                                # CLI
claude plugin list | grep -i orca      # Claude plugin version
codex plugin list | grep -i orca       # Codex plugin version (if applicable)
orca daemon status                     # daemon picked up the new binary
```

All three (or four) version strings should match. Compare to the values captured in the version-skew check above.

### Resume interrupted runs (if any)

```bash
orca runs
```

For any run shown as `interrupted`, ask the user before resuming:

```bash
orca resume <run_id>
```

### Done

Report to the user:
- CLI: old version → new version
- Plugin(s): old version → new version
- Whether Claude Code / Codex needs a restart (yes, if you updated the plugin)
- Which projects had their daemons restarted
- Any runs that were interrupted/resumed
- reminder to reload MCP in the editor if applicable
