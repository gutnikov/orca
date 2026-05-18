"""orca test subcommand: list, run, scaffold tests under .orca/tests/."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

_SKELETON_TEST_FLOW = """\
# Test workflow scaffold — fill in the body states before running.
# Shape: <slice under test> -> evaluate.
# The worktree is checked out from the state_ref declared in input.md.

issue:
  fields:
    title:
      type: string
      description: "Issue title (seeded from input.md frontmatter)"
    description:
      type: string
      description: "Issue description"

max_hops: 10
max_worker_retries: 2

initial: TODO_BODY_STATE   # rename to the slice's entry state

states:

  # TODO: copy body states from the production workflow here.
  # Outgoing routes that would leave the slice (or go to `done`) must
  # be rewritten to `evaluate`.

  evaluate:
    worker:
      kind: claude-code
      prompt:
        text: |
          # Evaluate
          Read tests/{{ run.test_name }}/evaluations.md, grade each criterion,
          write {{ run.run_dir }}/report.md, then write {{ result_path }}.

          ```json
          {{ result_example | tojson(indent=2) }}
          ```
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [passed, failed, inconclusive]
        criteria:
          type: list
          items: "string"
    on:
      passed: done
      failed: done
      inconclusive: done
"""

_SKELETON_INPUT = """\
---
title: "TODO: a one-line title for the test scenario"
description: |
  TODO: a one-paragraph description of the situation the slice should handle.
state_ref: TODO_STATE_REF
---

# Scenario

TODO: describe (for a human reader) what this test asserts and how the
state branch is arranged. The state branch checked out into the run
worktree is whatever `state_ref` above points at — edit the state
under `.orca-state/test-states/<name>/` and commit with plain git.
"""

_SKELETON_EVALUATIONS = """\
# Evaluations: TODO

TODO: one paragraph describing what this test asserts overall.

## Criteria

### criterion-id-here
TODO: a sentence stating one concrete, gradeable thing the result must satisfy.
"""


@dataclass(frozen=True)
class TestPaths:
    config_path: Path
    task_file: Path


def parse_state_ref(task_file: Path) -> str | None:
    """Return the `state_ref` frontmatter value from a test input.md.

    Returns None if the field is missing or still holds the placeholder
    `TODO_STATE_REF` that the scaffold writes initially.
    """
    from orca.orchestrator.runner import parse_task_file

    fields = parse_task_file(task_file)
    value = fields.get("state_ref")
    if not isinstance(value, str):
        return None
    if value == "TODO_STATE_REF":
        return None
    return value


def _create_state_branch_and_worktree(repo_root: Path, name: str) -> Path:
    """Create `orca-test-state/<name>` as an orphan branch + worktree.

    Returns the worktree path. Does NOT mutate the main repo's HEAD.

    Mechanic: create a detached worktree at the target location, switch to an
    orphan branch inside it, clear the worktree, commit one empty commit.
    The main repo's working tree and HEAD are untouched throughout.
    """
    branch = f"orca-test-state/{name}"
    worktree_path = repo_root / ".orca-state" / "test-states" / name

    check = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", branch],
        capture_output=True,
    )
    if check.returncode == 0:
        msg = f"state branch already exists: {branch}"
        raise FileExistsError(msg)

    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(worktree_path), "HEAD"],
        check=True,
        capture_output=True,
    )

    try:
        subprocess.run(
            ["git", "-C", str(worktree_path), "checkout", "--orphan", branch],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(worktree_path), "rm", "-rf", "--quiet", "."],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(worktree_path),
                "commit",
                "--allow-empty",
                "-m",
                f"init: orca test state for {name}",
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree_path)],
            capture_output=True,
        )
        raise

    return worktree_path


def scaffold_test(repo_root: Path, name: str) -> Path:
    """Create `.orca/tests/<name>/` with skeleton files. Returns the directory.

    Also creates `orca-test-state/<name>` (orphan branch) and a persistent
    author worktree at `.orca-state/test-states/<name>/`. The state_ref
    marker pointing at that branch is stamped into input.md.
    """
    if not _KEBAB_RE.match(name):
        msg = f"test name must be kebab-case (lowercase + hyphens), got {name!r}"
        raise ValueError(msg)

    test_dir = repo_root / ".orca" / "tests" / name
    if test_dir.exists():
        msg = f"test directory already exists: {test_dir}"
        raise FileExistsError(msg)

    _create_state_branch_and_worktree(repo_root, name)

    test_dir.mkdir(parents=True)
    input_text = _SKELETON_INPUT.replace("TODO_STATE_REF", f"orca-test-state/{name}")
    (test_dir / "test-flow.yml").write_text(_SKELETON_TEST_FLOW)
    (test_dir / "input.md").write_text(input_text)
    (test_dir / "evaluations.md").write_text(_SKELETON_EVALUATIONS)
    return test_dir


def list_tests(repo_root: Path) -> list[str]:
    """Return sorted list of test names under .orca/tests/."""
    tests_dir = repo_root / ".orca" / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(d.name for d in tests_dir.iterdir() if d.is_dir() and (d / "test-flow.yml").exists())


def resolve_test_paths(repo_root: Path, name: str) -> TestPaths:
    """Resolve the canonical files for a test by name."""
    test_dir = repo_root / ".orca" / "tests" / name
    config_path = test_dir / "test-flow.yml"
    if not config_path.exists():
        msg = f"test '{name}' not found: {config_path} does not exist"
        raise FileNotFoundError(msg)
    task_file = test_dir / "input.md"
    return TestPaths(config_path=config_path.resolve(), task_file=task_file.resolve())


async def _submit_run(repo_root: Path, config_path: Path, task_file: Path) -> str:
    """POST to the daemon to start a run. Returns the run_id."""
    from orca.daemon.lifecycle import socket_path

    sock = socket_path(repo_root)
    connector = aiohttp.UnixConnector(path=str(sock))
    payload: dict[str, Any] = {
        "task_file": str(task_file),
        "workflow": str(config_path),
        "branch": None,
        "base": None,
        "run_id": None,
        "headless": True,
        "insights": False,
    }
    async with (
        aiohttp.ClientSession(connector=connector) as session,
        session.post("http://localhost/api/runs/start", json=payload) as resp,
    ):
        body = await resp.json()
        if resp.status not in (200, 201):
            msg = body.get("error", json.dumps(body))
            raise RuntimeError(f"daemon error: {msg}")
        return str(body["run_id"])


def run_test(repo_root: Path, name: str) -> str:
    """Submit a test run to the daemon. Returns the run_id."""
    paths = resolve_test_paths(repo_root, name)
    return asyncio.run(_submit_run(repo_root, paths.config_path, paths.task_file))


def test_command(args: Namespace, root: Path | None = None) -> None:
    """Dispatch `orca test` based on args.args and args.all."""
    from orca.cli.daemon_cmd import _repo_root

    repo = _repo_root(root)
    sub_args: list[str] = list(args.args)

    if args.all:
        names = list_tests(repo)
        if not names:
            print("No tests found under .orca/tests/.", file=sys.stderr)
            raise SystemExit(1)
        for name in names:
            try:
                run_id = run_test(repo, name)
            except (FileNotFoundError, RuntimeError) as exc:
                print(f"{name}: error: {exc}", file=sys.stderr)
                continue
            print(f"{name}: started (run_id={run_id})")
        return

    if sub_args and sub_args[0] == "add":
        if len(sub_args) != 2:
            print("Usage: orca test add <name>", file=sys.stderr)
            raise SystemExit(2)
        name = sub_args[1]
        try:
            path = scaffold_test(repo, name)
        except (ValueError, FileExistsError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        wt = repo / ".orca-state" / "test-states" / name
        print(f"Scaffolded: {path}")
        print(f"State branch: orca-test-state/{name}")
        print(f"Author worktree: {wt}")
        print()
        print("Next:")
        print(f"  cd {wt}")
        print("  # arrange your test state, then:")
        print('  git add . && git commit -m "seed: <describe scenario>"')
        print(f"  # then: orca test {name}")
        return

    if sub_args:
        if len(sub_args) != 1:
            print("Usage: orca test <name>", file=sys.stderr)
            raise SystemExit(2)
        try:
            run_id = run_test(repo, sub_args[0])
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Run started: {run_id}")
        return

    names = list_tests(repo)
    if not names:
        print("No tests found under .orca/tests/.")
        return
    for name in names:
        print(name)
