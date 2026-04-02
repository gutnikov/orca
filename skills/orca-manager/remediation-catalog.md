# Remediation Catalog

Known environment and infrastructure issues with tested fixes. Match error patterns from worker logs against entries below.

## Orca Daemon

### Daemon not running

**Pattern:** `orca_daemon_status()` MCP call fails, or `Connection refused` when any `orca_*` MCP tool is called
**Platform:** both
**Fix:**
- Start daemon in target project: `cd <target_project> && orca daemon start`
- Wait 3s, verify with `orca_daemon_status()`
**Verify:** `orca_daemon_status()` returns uptime and run count
**Risk:** low

### Daemon crashed (stale pidfile)

**Pattern:** Daemon was running but MCP tools suddenly fail. `.orca/daemon.pid` exists but process is dead.
**Platform:** both
**Fix:**
- Check process: `cat <target_project>/.orca/daemon.pid` then `kill -0 <pid>` (fails if dead)
- Clean up: `rm <target_project>/.orca/daemon.pid <target_project>/.orca/daemon.sock`
- Restart: `cd <target_project> && orca daemon start`
- Resume runs: `orca_list_runs()` to find stopped runs, `orca_resume_run()` for each
**Verify:** `orca_daemon_status()` succeeds, runs resumed
**Risk:** low

### Daemon unresponsive

**Pattern:** `.orca/daemon.pid` exists, process is alive, but MCP tools timeout or return errors
**Platform:** both
**Fix:**
- Wait 10 seconds and retry — may be transient (heavy load)
- If persists: `cd <target_project> && orca daemon stop && sleep 2 && orca daemon start`
- Resume any affected runs
**Verify:** `orca_daemon_status()` responds promptly
**Risk:** low

## Docker

### Docker daemon not running

**Pattern:** `Cannot connect to the Docker daemon` or `Is the docker daemon running?`
**Platform:** both
**Fix:**
- macOS: `open -a Docker && sleep 15 && docker info`
- Linux: `sudo systemctl start docker && sleep 5 && docker info`
**Verify:** `docker info` exits 0
**Risk:** low

### Docker image pull failure

**Pattern:** `Error response from daemon: pull access denied` or `manifest unknown`
**Platform:** both
**Fix:**
- Check image name/tag spelling in the project's docker-compose or Dockerfile
- If auth required: report to user — do not attempt `docker login` autonomously
**Verify:** `docker pull <image>` succeeds
**Risk:** low (read-only diagnosis), medium (if fixing image references)

## Node / npm

### Node.js not installed

**Pattern:** `node: command not found` or `npm: command not found`
**Platform:** both
**Fix:**
- macOS: `brew install node`
- Linux: `curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs`
- Or if `.nvmrc` exists: `nvm install && nvm use`
**Verify:** `node --version && npm --version`
**Risk:** low

### npm install failure

**Pattern:** `npm ERR! code ERESOLVE` or `npm ERR! peer dep`
**Platform:** both
**Fix:**
- Try `npm install --legacy-peer-deps`
- If lockfile conflict: `rm -rf node_modules package-lock.json && npm install`
**Verify:** `npm install` exits 0
**Risk:** medium (lockfile deletion)

## Git

### Worktree conflict

**Pattern:** `fatal: '...' is already checked out` or `fatal: working tree '...' already exists`
**Platform:** both
**Fix:**
- List worktrees: `git worktree list`
- If stale: `git worktree prune`
- If active but blocking: report to user — don't remove active worktrees
**Verify:** `git worktree list` shows no conflicts for the target path
**Risk:** low (prune), high (remove — never do autonomously)

### Detached HEAD in worktree

**Pattern:** `HEAD detached at` in worktree used by orca
**Platform:** both
**Fix:**
- Check which branch the run expects: `git branch --show-current` in the worktree
- If detached: `git checkout <expected-branch>` in the worktree
**Verify:** `git branch --show-current` returns expected branch
**Risk:** low

## Ports

### Port already in use

**Pattern:** `EADDRINUSE` or `address already in use` or `bind: address already in use`
**Platform:** both
**Fix:**
- Identify what's using the port: `lsof -i :<port>` (macOS/Linux)
- Report process name and PID to user — never kill unknown processes
- If the process is a known dev server from a previous run: suggest user kills it
**Verify:** `lsof -i :<port>` returns empty
**Risk:** low (diagnosis only)

## Disk

### Disk space exhausted

**Pattern:** `No space left on device` or `ENOSPC`
**Platform:** both
**Fix:**
- Check space: `df -h .`
- Report to user with breakdown — do not delete files autonomously
- Suggest: docker image prune, npm cache clean, git gc
**Verify:** `df -h .` shows reasonable free space
**Risk:** low (diagnosis only)

## Permissions

### File permission denied

**Pattern:** `EACCES` or `Permission denied` (on local file operations)
**Platform:** both
**Fix:**
- Identify the file: path is usually in the error message
- If it's a script that needs execute: `chmod +x <path>`
- If it's a directory access issue: report to user
**Verify:** `ls -la <path>` shows correct permissions
**Risk:** low (chmod +x on scripts), medium (broader permission changes)

## Python / venv

### Python venv missing or broken

**Pattern:** `ModuleNotFoundError` for project deps, or `No module named` in orca context
**Platform:** both
**Fix:**
- In orca repo: `uv sync`
- In target project: check for `requirements.txt`, `pyproject.toml`, or `Pipfile` and run appropriate install
**Verify:** `uv run python -c "import <module>"` succeeds
**Risk:** low

## Environment Variables

### Missing environment variable

**Pattern:** `KeyError: '<VAR_NAME>'` or `Environment variable <VAR> not set` or `<VAR> is required`
**Platform:** both
**Fix:**
- Check if `.env` or `.env.example` exists in the target project
- If `.env.example` exists but `.env` doesn't: `cp .env.example .env` and report to user to fill in values
- If the var is an API key or secret: always report to user — never fabricate credentials
**Verify:** `echo $<VAR_NAME>` returns non-empty
**Risk:** low (diagnosis), medium (copying .env template)

## DNS / Network

### DNS resolution failure

**Pattern:** `ENOTFOUND` or `getaddrinfo` or `Name or service not known`
**Platform:** both
**Fix:**
- Check basic connectivity: `ping -c 1 8.8.8.8`
- If ping works but DNS fails: likely a DNS config issue — report to user
- If ping fails: network is down — classify as TRANSIENT, wait and retry
**Verify:** `nslookup <hostname>` resolves
**Risk:** low (diagnosis only)
