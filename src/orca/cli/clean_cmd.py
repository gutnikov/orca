"""orca clean — remove terminal-state runs and accumulated artifacts."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import aiohttp

TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped", "interrupted"})


def clean_command(
    root: Path | None = None,
    *,
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    """Remove terminal-state runs, their worktrees, and stale temp files.

    Skips RUNNING runs entirely. If the daemon is up, drops via its API so its
    in-memory tracking stays consistent; then removes the on-disk run dir
    (which the daemon's drop leaves behind), the worktree (via git), and any
    leftover temp files.
    """
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    state_dir = repo / ".orca-state"

    if not state_dir.exists():
        print("Nothing to clean: .orca-state/ does not exist.")
        return

    daemon_running = check_daemon_running(repo)
    sock = socket_path(repo) if daemon_running else None

    if daemon_running:
        assert sock is not None
        terminal_runs, active_runs = asyncio.run(_classify_runs_via_daemon(sock))
    else:
        terminal_runs, active_runs = _classify_runs_on_disk(state_dir)

    worktrees_dir = state_dir / "worktrees"
    worktrees_to_remove: list[Path] = []
    if worktrees_dir.exists() and not active_runs:
        worktrees_to_remove = sorted(p for p in worktrees_dir.iterdir() if p.is_dir())

    temp_files = sorted(state_dir.rglob(".prompt-*.tmp"))

    bytes_freed = 0
    for run in terminal_runs:
        bytes_freed += _dir_size(state_dir / "runs" / run["branch"] / run["workflow"])
    for wt in worktrees_to_remove:
        bytes_freed += _dir_size(wt)
    for tmp in temp_files:
        with contextlib.suppress(OSError):
            bytes_freed += tmp.stat().st_size

    if not terminal_runs and not worktrees_to_remove and not temp_files:
        print("Nothing to clean.")
        return

    print("Will clean:")
    if terminal_runs:
        print(f"  {len(terminal_runs)} run(s) in terminal state:")
        for run in terminal_runs[:20]:
            print(f"    - {run['run_id']} [{run['status']}]")
        if len(terminal_runs) > 20:
            print(f"    ... and {len(terminal_runs) - 20} more")
    if worktrees_to_remove:
        print(f"  {len(worktrees_to_remove)} worktree(s) under .orca-state/worktrees/")
    if temp_files:
        print(f"  {len(temp_files)} temp file(s)")
    print(f"  ~{_format_size(bytes_freed)} freed")

    if active_runs:
        print(f"\nKeeping {len(active_runs)} active run(s):")
        for run in active_runs:
            print(f"  - {run['run_id']} [{run['status']}]")

    if not daemon_running:
        print("\nNote: daemon is not running — treating all on-disk runs as terminal.")

    if dry_run:
        print("\n(dry run — nothing deleted)")
        return

    if not yes:
        try:
            answer = input("\nProceed? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    drops_via_daemon = 0
    if daemon_running and terminal_runs:
        assert sock is not None
        drops_via_daemon = asyncio.run(_drop_runs_via_daemon(sock, terminal_runs))

    runs_removed = 0
    for run in terminal_runs:
        run_dir = state_dir / "runs" / run["branch"] / run["workflow"]
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
            runs_removed += 1
        parent = run_dir.parent
        if parent.exists() and not any(parent.iterdir()):
            with contextlib.suppress(OSError):
                parent.rmdir()

    worktrees_removed = 0
    for wt in worktrees_to_remove:
        if _remove_worktree(repo, wt):
            worktrees_removed += 1

    if worktrees_to_remove:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(repo),
            capture_output=True,
            check=False,
        )

    temps_removed = 0
    for tmp in temp_files:
        try:
            tmp.unlink()
            temps_removed += 1
        except OSError:
            pass

    summary = f"Cleaned: {runs_removed} run(s), {worktrees_removed} worktree(s), {temps_removed} temp file(s)."
    if daemon_running and terminal_runs:
        summary += f" Daemon dropped {drops_via_daemon}/{len(terminal_runs)} via API."
    print(summary)


async def _classify_runs_via_daemon(
    sock: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Query the daemon and split runs into (terminal, active)."""
    connector = aiohttp.UnixConnector(path=str(sock))
    async with (
        aiohttp.ClientSession(connector=connector) as session,
        session.get("http://localhost/api/runs") as resp,
    ):
        if resp.status != 200:
            print(f"Error: daemon returned {resp.status} for /api/runs", file=sys.stderr)
            raise SystemExit(1)
        runs: list[dict[str, Any]] = await resp.json()

    terminal = [r for r in runs if r["status"].lower() in TERMINAL_STATUSES]
    active = [r for r in runs if r["status"].lower() == "running"]
    return terminal, active


def _classify_runs_on_disk(
    state_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """When daemon is down, scan .orca-state/runs/ — treat every run as terminal."""
    runs_dir = state_dir / "runs"
    if not runs_dir.exists():
        return [], []

    found: list[dict[str, Any]] = []
    for branch_dir in runs_dir.iterdir():
        if not branch_dir.is_dir():
            continue
        for workflow_dir in branch_dir.iterdir():
            if not workflow_dir.is_dir():
                continue
            if not (workflow_dir / "state.json").exists():
                continue
            found.append(
                {
                    "run_id": f"{branch_dir.name}:{workflow_dir.name}",
                    "branch": branch_dir.name,
                    "workflow": workflow_dir.name,
                    "status": "interrupted",
                }
            )
    return found, []


async def _drop_runs_via_daemon(sock: Path, runs: list[dict[str, Any]]) -> int:
    """POST /api/runs/{id}/drop for each run; return count of successes."""
    connector = aiohttp.UnixConnector(path=str(sock))
    success = 0
    async with aiohttp.ClientSession(connector=connector) as session:
        for run in runs:
            try:
                async with session.post(f"http://localhost/api/runs/{run['run_id']}/drop") as resp:
                    if resp.status == 200:
                        success += 1
            except aiohttp.ClientError:
                pass
    return success


def _remove_worktree(repo: Path, worktree_path: Path) -> bool:
    """Try `git worktree remove --force`, fall back to rm -rf."""
    result = subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)
    return not worktree_path.exists()


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    with contextlib.suppress(OSError):
        for p in path.rglob("*"):
            if p.is_file():
                with contextlib.suppress(OSError):
                    total += p.stat().st_size
    return total


def _format_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"
