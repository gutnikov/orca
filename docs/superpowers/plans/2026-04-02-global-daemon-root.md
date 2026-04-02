# Global `--root` and `~/.orca/` Daemon State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move daemon PID/socket files to `~/.orca/daemons/{repo_hash}/` and add a global `--root` CLI flag so orca can manage any repo from any directory.

**Architecture:** The `lifecycle.py` module gets a new `daemon_dir(repo_root)` function that maps a repo path to `~/.orca/daemons/{sha1_hex[:12]}/`. A `root` file inside that dir stores the absolute repo path for reverse lookup. The `_repo_root()` function in `daemon_cmd.py` gains an optional `root_override` parameter. The CLI parser adds `--root` as a top-level argument passed to all subcommands.

**Tech Stack:** Python 3.12, argparse, hashlib, pathlib

---

### Task 1: New `daemon_dir()` function in lifecycle.py

**Files:**
- Modify: `src/orca/daemon/lifecycle.py:18-25`
- Test: `tests/daemon/test_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/daemon/test_lifecycle.py

import hashlib

from orca.daemon.lifecycle import daemon_dir


class TestDaemonDir:
    def test_returns_path_under_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = Path("/Users/alice/work/myrepo")
        result = daemon_dir(repo)
        repo_hash = hashlib.sha1(str(repo).encode()).hexdigest()[:12]
        assert result == fake_home / ".orca" / "daemons" / repo_hash

    def test_deterministic(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = Path("/Users/alice/work/myrepo")
        assert daemon_dir(repo) == daemon_dir(repo)

    def test_different_repos_different_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        assert daemon_dir(Path("/repo/a")) != daemon_dir(Path("/repo/b"))
```

Add `import pytest` at top of test file if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_lifecycle.py::TestDaemonDir -v`
Expected: FAIL — `cannot import name 'daemon_dir' from 'orca.daemon.lifecycle'`

- [ ] **Step 3: Implement `daemon_dir()`**

Add to `src/orca/daemon/lifecycle.py` after the imports:

```python
import hashlib

def daemon_dir(repo_root: Path) -> Path:
    """Return ~/.orca/daemons/{hash}/ for the given repo root."""
    repo_hash = hashlib.sha1(str(repo_root).encode()).hexdigest()[:12]
    return Path.home() / ".orca" / "daemons" / repo_hash
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_lifecycle.py::TestDaemonDir -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/daemon/lifecycle.py tests/daemon/test_lifecycle.py
git commit -m "feat(daemon): add daemon_dir() for ~/.orca/daemons/{hash} paths"
```

---

### Task 2: Update `socket_path()` and `pidfile_path()` to use `daemon_dir()`

**Files:**
- Modify: `src/orca/daemon/lifecycle.py:18-25`
- Modify: `tests/daemon/test_lifecycle.py:45-50`

- [ ] **Step 1: Update the existing path tests**

Update `TestPaths` in `tests/daemon/test_lifecycle.py`:

```python
class TestPaths:
    def test_socket_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        expected = daemon_dir(repo) / "daemon.sock"
        assert socket_path(repo) == expected

    def test_pidfile_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        expected = daemon_dir(repo) / "daemon.pid"
        assert pidfile_path(repo) == expected
```

Update the import at the top to include `daemon_dir`:

```python
from orca.daemon.lifecycle import (
    DaemonAlreadyRunningError,
    check_daemon_running,
    cleanup_stale_socket,
    daemon_dir,
    pidfile_path,
    read_pidfile,
    remove_pidfile,
    send_stop_signal,
    socket_path,
    write_pidfile,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_lifecycle.py::TestPaths -v`
Expected: FAIL — paths still point to `{repo}/.orca/`

- [ ] **Step 3: Update `socket_path()` and `pidfile_path()`**

In `src/orca/daemon/lifecycle.py`, change:

```python
def socket_path(repo_root: Path) -> Path:
    """Return the UDS socket path for the given repo."""
    return daemon_dir(repo_root) / "daemon.sock"


def pidfile_path(repo_root: Path) -> Path:
    """Return the pidfile path for the given repo."""
    return daemon_dir(repo_root) / "daemon.pid"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_lifecycle.py::TestPaths -v`
Expected: PASS

- [ ] **Step 5: Fix remaining lifecycle tests that assume old paths**

The `TestCheckDaemonRunning`, `TestCleanupStaleSocket`, and `TestSendStopSignal` tests create files at `{tmp_path}/.orca/`. These now need to create them at the `daemon_dir()` location. Update each test to use `monkeypatch` for HOME and create files at the correct path. For example:

```python
class TestCheckDaemonRunning:
    def test_not_running_no_pidfile(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        dd = daemon_dir(repo)
        dd.mkdir(parents=True)
        assert check_daemon_running(repo) is False

    def test_not_running_stale_pid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        pf = pidfile_path(repo)
        pf.parent.mkdir(parents=True, exist_ok=True)
        write_pidfile(pf, 99999999)
        assert check_daemon_running(repo) is False
        assert not pf.exists()

    def test_running(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        pf = pidfile_path(repo)
        pf.parent.mkdir(parents=True, exist_ok=True)
        write_pidfile(pf, os.getpid())
        assert check_daemon_running(repo) is True


class TestCleanupStaleSocket:
    def test_removes_stale_socket(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        sock = socket_path(repo)
        sock.parent.mkdir(parents=True, exist_ok=True)
        sock.touch()
        cleanup_stale_socket(repo)
        assert not sock.exists()

    def test_noop_when_no_socket(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        daemon_dir(repo).mkdir(parents=True, exist_ok=True)
        cleanup_stale_socket(repo)


class TestSendStopSignal:
    def test_returns_false_when_no_pidfile(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        daemon_dir(repo).mkdir(parents=True, exist_ok=True)
        assert send_stop_signal(repo) is False

    def test_returns_false_when_stale_pid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        pf = pidfile_path(repo)
        pf.parent.mkdir(parents=True, exist_ok=True)
        write_pidfile(pf, 99999999)
        assert send_stop_signal(repo) is False
```

- [ ] **Step 6: Run full lifecycle test suite**

Run: `uv run pytest tests/daemon/test_lifecycle.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/daemon/lifecycle.py tests/daemon/test_lifecycle.py
git commit -m "refactor(daemon): move pidfile and socket to ~/.orca/daemons/{hash}"
```

---

### Task 3: Write `root` marker file in daemon dir

The daemon should write a `root` file containing the absolute repo path into `daemon_dir()` on startup, so we can reverse-lookup which repo a daemon serves.

**Files:**
- Modify: `src/orca/daemon/lifecycle.py`
- Modify: `src/orca/daemon/server.py:44-46`
- Modify: `tests/daemon/test_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/daemon/test_lifecycle.py`:

```python
from orca.daemon.lifecycle import write_root_marker, read_root_marker


class TestRootMarker:
    def test_write_and_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        repo = tmp_path / "repo"
        write_root_marker(repo)
        assert read_root_marker(daemon_dir(repo)) == repo

    def test_read_missing(self, tmp_path: Path) -> None:
        assert read_root_marker(tmp_path / "nonexistent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_lifecycle.py::TestRootMarker -v`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement in lifecycle.py**

```python
def write_root_marker(repo_root: Path) -> None:
    """Write the repo root path into the daemon dir for reverse lookup."""
    dd = daemon_dir(repo_root)
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "root").write_text(str(repo_root) + "\n")


def read_root_marker(dd: Path) -> Path | None:
    """Read the repo root from a daemon dir's root marker file."""
    root_file = dd / "root"
    try:
        return Path(root_file.read_text().strip())
    except FileNotFoundError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_lifecycle.py::TestRootMarker -v`
Expected: PASS

- [ ] **Step 5: Call `write_root_marker()` in server.py**

In `src/orca/daemon/server.py`, add to the import from `orca.daemon.lifecycle`:

```python
from orca.daemon.lifecycle import (
    DaemonAlreadyRunningError,
    check_daemon_running,
    cleanup_stale_socket,
    pidfile_path,
    remove_pidfile,
    socket_path,
    write_pidfile,
    write_root_marker,
)
```

Then after `write_pidfile(pf, os.getpid())` (line 46), add:

```python
    write_root_marker(repo_root)
```

- [ ] **Step 6: Run full daemon tests**

Run: `uv run pytest tests/daemon/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/daemon/lifecycle.py src/orca/daemon/server.py tests/daemon/test_lifecycle.py
git commit -m "feat(daemon): write root marker file for reverse repo lookup"
```

---

### Task 4: Add `--root` global CLI argument

**Files:**
- Modify: `src/orca/cli/main.py:30-79`
- Modify: `src/orca/cli/daemon_cmd.py:11-29`
- Test: `tests/cli/test_main.py`

- [ ] **Step 1: Read existing CLI tests**

Read `tests/cli/test_main.py` to understand current test patterns before modifying.

- [ ] **Step 2: Add `--root` to the top-level parser**

In `src/orca/cli/main.py`, add after the `--version` argument (line 33):

```python
    parser.add_argument("--root", type=Path, default=None, help="Repository root (default: auto-detect via git)")
```

- [ ] **Step 3: Refactor `_repo_root()` to accept override**

In `src/orca/cli/daemon_cmd.py`, change:

```python
def _repo_root(override: Path | None = None) -> Path:
    """Return the repo root — from explicit override or git rev-parse."""
    if override is not None:
        resolved = override.resolve()
        if not resolved.is_dir():
            print(f"Error: --root path does not exist: {resolved}", file=sys.stderr)
            raise SystemExit(1)
        return resolved
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print("Error: not inside a git repository. Use --root to specify the repo.", file=sys.stderr)
        raise SystemExit(1)
    return Path(result.stdout.strip())
```

- [ ] **Step 4: Update `daemon_command()` to accept root**

```python
def daemon_command(action: str, root: Path | None = None) -> None:
    """Dispatch daemon start/stop/status."""
    from orca.daemon.lifecycle import check_daemon_running, pidfile_path, read_pidfile, send_stop_signal

    repo = _repo_root(root)
    # ... rest unchanged
```

- [ ] **Step 5: Pass `args.root` from main.py dispatcher**

In `src/orca/cli/main.py`, update the daemon dispatch:

```python
    if args.subcommand == "daemon":
        from orca.cli.daemon_cmd import daemon_command

        daemon_command(args.daemon_action, root=args.root)
```

For all other subcommands, pass `root=args.root` through. Each subcommand handler will need updating in the next task.

- [ ] **Step 6: Run lint and type-check**

Run: `uv run ruff check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/cli/main.py src/orca/cli/daemon_cmd.py
git commit -m "feat(cli): add global --root flag for repo path override"
```

---

### Task 5: Update all CLI subcommands to accept `root`

Every CLI command that calls `_repo_root()` needs to accept the `root` override. The pattern is identical in each file: add a `root: Path | None = None` parameter and pass it to `_repo_root(root)`.

**Files:**
- Modify: `src/orca/cli/mcp_cmd.py`
- Modify: `src/orca/cli/run_cmd.py`
- Modify: `src/orca/cli/tui_cmd.py`
- Modify: `src/orca/cli/list_cmd.py`
- Modify: `src/orca/cli/stop_cmd.py`
- Modify: `src/orca/cli/drop_cmd.py`
- Modify: `src/orca/cli/resume_cmd.py`
- Modify: `src/orca/cli/main.py:95-142`

- [ ] **Step 1: Update mcp_cmd.py**

```python
def mcp_command(root: Path | None = None) -> None:
    """Create an MCP server backed by DaemonClient, run on stdio transport."""
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.client import DaemonClient
    from orca.daemon.lifecycle import check_daemon_running, socket_path
    from orca.daemon.mcp_tools import create_mcp_server

    repo = _repo_root(root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    client = DaemonClient(socket_path(repo))
    server = create_mcp_server(client)
    server.run(transport="stdio")
```

Add `from pathlib import Path` to imports.

- [ ] **Step 2: Update run_cmd.py**

```python
def run_command(args: Namespace) -> None:
    """Check daemon running, POST /api/runs/start, print run_id or error."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(args.root)
    # ... rest unchanged
```

`args.root` is already available via the top-level parser — no extra work needed.

- [ ] **Step 3: Update tui_cmd.py**

```python
def tui_command(root: Path | None = None) -> None:
    """Check daemon running, launch OrcaApp connected to daemon."""
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    # ... rest unchanged
```

Add `from pathlib import Path` to imports.

- [ ] **Step 4: Update stop_cmd.py**

```python
def stop_command(run_id: str, root: Path | None = None) -> None:
    """POST /api/runs/{run_id}/stop to the daemon."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    # ... rest unchanged
```

Add `from pathlib import Path` to imports.

- [ ] **Step 5: Update drop_cmd.py**

Same pattern — add `root: Path | None = None` parameter, pass to `_repo_root(root)`. Add `from pathlib import Path`.

- [ ] **Step 6: Update resume_cmd.py**

Same pattern — add `root: Path | None = None` parameter, pass to `_repo_root(root)`. Add `from pathlib import Path`.

- [ ] **Step 7: Update list_cmd.py**

Both `runs_command()` and `logs_command()`:

```python
def runs_command(root: Path | None = None) -> None:
    # ...
    repo = _repo_root(root)
```

```python
def logs_command(args: Namespace) -> None:
    # ...
    repo = _repo_root(args.root)
```

Add `from pathlib import Path` to imports.

- [ ] **Step 8: Update main.py dispatcher to pass root through**

```python
    if args.subcommand == "daemon":
        from orca.cli.daemon_cmd import daemon_command
        daemon_command(args.daemon_action, root=args.root)

    elif args.subcommand == "run":
        from orca.cli.run_cmd import run_command
        run_command(args)  # args.root is already in args

    elif args.subcommand == "tui":
        from orca.cli.tui_cmd import tui_command
        tui_command(root=args.root)

    elif args.subcommand == "mcp":
        from orca.cli.mcp_cmd import mcp_command
        mcp_command(root=args.root)

    elif args.subcommand == "stop":
        from orca.cli.stop_cmd import stop_command
        stop_command(args.run_id, root=args.root)

    elif args.subcommand == "drop":
        from orca.cli.drop_cmd import drop_command
        drop_command(args.run_id, root=args.root)

    elif args.subcommand == "resume":
        from orca.cli.resume_cmd import resume_command
        resume_command(args.run_id, root=args.root)

    elif args.subcommand == "runs":
        from orca.cli.list_cmd import runs_command
        runs_command(root=args.root)

    elif args.subcommand == "logs":
        from orca.cli.list_cmd import logs_command
        logs_command(args)  # args.root is already in args
```

- [ ] **Step 9: Run lint, type-check, and full test suite**

Run: `uv run ruff check . && uv run mypy src/ && uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add src/orca/cli/
git commit -m "feat(cli): pass --root through all subcommands"
```

---

### Task 6: Update `bin/orca-mcp.sh` to use `--root`

**Files:**
- Modify: `bin/orca-mcp.sh`

- [ ] **Step 1: Simplify the script**

```bash
#!/bin/bash
# Launch orca MCP server.
# Usage: orca-mcp.sh [repo-root]
#   repo-root: optional repo root path (passed as --root to orca mcp)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ORCA_BIN="${SCRIPT_DIR}/../.venv/bin/orca"

if [ ! -f "$ORCA_BIN" ]; then
  echo "orca binary not found at $ORCA_BIN — run 'uv sync' in $(dirname "$SCRIPT_DIR")" >&2
  exit 1
fi

if [ -n "$1" ]; then
  exec "$ORCA_BIN" --root "$1" mcp
else
  exec "$ORCA_BIN" mcp
fi
```

- [ ] **Step 2: Verify script is executable**

Run: `chmod +x bin/orca-mcp.sh`

- [ ] **Step 3: Commit**

```bash
git add bin/orca-mcp.sh
git commit -m "feat(bin): use --root flag in orca-mcp.sh"
```

---

### Task 7: Run full test suite and lint

**Files:** None (verification only)

- [ ] **Step 1: Run ruff**

Run: `uv run ruff check .`
Expected: PASS

- [ ] **Step 2: Run ruff format check**

Run: `uv run ruff format --check .`
Expected: PASS (fix any formatting issues if needed)

- [ ] **Step 3: Run mypy**

Run: `uv run mypy src/`
Expected: PASS

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 5: Commit any fixes**

If any lint/type fixes were needed, commit them:

```bash
git add -u
git commit -m "fix: lint and type-check fixes for --root feature"
```
