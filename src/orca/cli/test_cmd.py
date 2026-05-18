"""orca test subcommand: list, run, scaffold tests under .orca/tests/."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

_SKELETON_TEST_FLOW = """\
# Test workflow scaffold — fill in the body states before running.
# Bookended shape: setup -> <slice under test> -> evaluate.

issue:
  fields:
    title:
      type: string
      description: "Issue title (seeded by setup or input.md frontmatter)"
    description:
      type: string
      description: "Issue description"

max_hops: 10
max_worker_retries: 2

initial: setup

states:

  setup:
    worker:
      kind: claude-code
      prompt:
        text: |
          # Setup
          Read tests/{{ run.test_name }}/input.md and arrange the worktree.
          Write {{ result_path }} with the issue field values.

          ```json
          {{ result_example | tojson(indent=2) }}
          ```
      timeout: 300
      result_format:
        outcome:
          type: enum
          values: [ready, setup_failed]
        title:
          type: string
        description:
          type: string
    on:
      ready: TODO_BODY_STATE   # rename to the slice's entry state
      setup_failed: failed

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
---

# Scenario

TODO: describe the test scenario — what should the slice do, what does the
worktree need to look like beforehand, and what fixtures should setup copy in.
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


def scaffold_test(repo_root: Path, name: str) -> Path:
    """Create `.orca/tests/<name>/` with skeleton files. Returns the directory."""
    if not _KEBAB_RE.match(name):
        msg = f"test name must be kebab-case (lowercase + hyphens), got {name!r}"
        raise ValueError(msg)

    test_dir = repo_root / ".orca" / "tests" / name
    if test_dir.exists():
        msg = f"test directory already exists: {test_dir}"
        raise FileExistsError(msg)

    fixtures_dir = test_dir / "fixtures"
    fixtures_dir.mkdir(parents=True)
    (test_dir / "test-flow.yml").write_text(_SKELETON_TEST_FLOW)
    (test_dir / "input.md").write_text(_SKELETON_INPUT)
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
        try:
            path = scaffold_test(repo, sub_args[1])
        except (ValueError, FileExistsError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Scaffolded: {path}")
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
