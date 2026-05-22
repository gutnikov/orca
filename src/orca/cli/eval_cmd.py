"""orca eval subcommand: list, run, scaffold evals under .orca/evals/."""

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

_SKELETON_EVAL_FLOW = """\
# Eval workflow scaffold — fill in the body states before running.
# Shape: <slice under eval> -> assert.
# The worktree is checked out from the state_ref declared in input.md.

issue:
  fields:
    title:
      type: string
      description: "Issue title (seeded from input.md frontmatter)"
    description:
      type: string
      description: "Issue description"

initial: TODO_BODY_STATE   # rename to the slice's entry state

states:

  # TODO: copy body states from the production workflow here.
  # Outgoing routes that would leave the slice (or go to `done`) must
  # be rewritten to `assert`.

  assert:
    worker:
      kind: claude-code
      prompt:
        text: |
          # Assert
          Read {{ run.repo_root }}/.orca/evals/{{ run.eval_name }}/assertions.md, grade each criterion,
          write {{ run.run_dir }}/report.md, then write {{ result_path }}.

          ```json
          {{ result_example | tojson(indent=2) }}
          ```
      inactivity_timeout: 600
      result_format:
        outcome:
          type: enum
          values: [passed, failed, inconclusive]
        criteria:
          type: list
          items: "string"
    on:
      passed: review
      failed: review
      inconclusive: review

  review:
    worker:
      kind: claude-code
      prompt:
        text: |
          # Review

          You are assembling a human-review form for an eval that just finished.
          The form is comment-driven: the user reads the assertions and the
          worktree diff, leaves inline comments where they want changes, and
          submits. The agent then drives the prompt/assertion edits step-by-step
          from those comments — there are no action checkboxes on the form.

          1. Read {{ run.run_dir }}/report.md — it has a Markdown table
             `| ID | Status | Reason |` with one row per criterion.
          2. From the current working directory (already inside the eval
             worktree), run `git diff --no-color HEAD~3..HEAD --stat` to learn
             which files the worker changed, then `git diff` per file for the
             unified hunks. If there is no diff, the worktree is unchanged and
             the changeset block's `files` list should be empty.
          3. Emit `outcome: waiting` with the form below. Fill in:
             - `criteria`: one entry per row of the report table, mapping the
               row's status text to `"passed"` / `"failed"` / `"skipped"`
               exactly. `summary` is the row's reason text (first sentence is
               fine).
             - `files`: one entry per changed file with `path`, `status`
               (`added` / `modified` / `deleted` / `renamed`), `language`
               (best-effort from extension), `additions`, `deletions`, and
               `diff` (the unified diff hunks for that file).
          4. When the user submits, you will receive a JSON envelope on stdin.
             Parse it and write {{ result_path }} with:
             - `outcome: reviewed` if the user left at least one comment;
             - `outcome: skipped` if the user submitted with no comments or
               cancelled the form.
             - `comments`: the changeset block's line-anchored comments
               as a list of `"<path>:<line> <body>"` strings (may be empty).

          Form schema (copy this exact shape into your waiting payload, with
          the placeholders filled):

          ```json
          {
            "title": "Review eval results",
            "description": "Comment inline where you want changes; submit when done.",
            "submit_label": "Submit comments",
            "cancel_label": "Skip",
            "steps": [
              {
                "blocks": [
                  {
                    "kind": "markdown",
                    "content": "<one-line summary of report.md overall outcome>"
                  },
                  {"kind": "assertions", "criteria": []},
                  {"kind": "changeset", "name": "review", "files": []}
                ]
              }
            ]
          }
          ```

          Required result shape:

          ```json
          {{ result_example | tojson(indent=2) }}
          ```
      inactivity_timeout: 3600
      result_format:
        outcome:
          type: enum
          values: [reviewed, skipped]
          description: "Did the user leave any comments?"
          values_description:
            reviewed: "User submitted with at least one comment"
            skipped: "User submitted with no comments or cancelled"
        comments:
          type: list
          items: "string"
          description: "Line-anchored comments from the changeset block, formatted '<path>:<line> <body>'"
    on:
      reviewed: done
      skipped: done
"""

_SKELETON_INPUT = """\
---
title: "TODO: a one-line title for the eval scenario"
description: |
  TODO: a one-paragraph description of the situation the slice should handle.
state_ref: TODO_STATE_REF
---

# Scenario

TODO: describe (for a human reader) what this eval asserts and how the
state branch is arranged. The state branch checked out into the run
worktree is whatever `state_ref` above points at — edit the state
under `.orca-state/eval-states/<name>/` and commit with plain git.
"""

_SKELETON_ASSERTIONS = """\
# Assertions: TODO

TODO: one paragraph describing what this eval asserts overall.

## Criteria

### criterion-id-here
TODO: a sentence stating one concrete, gradeable thing the result must satisfy.
"""


@dataclass(frozen=True)
class EvalPaths:
    config_path: Path
    task_file: Path


def parse_state_ref(task_file: Path) -> str | None:
    """Return the `state_ref` frontmatter value from an eval input.md.

    Returns None if the field is missing or still holds the `TODO_STATE_REF`
    placeholder used by old or hand-written skeletons.
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
    """Create `orca-eval-state/<name>` as an orphan branch + worktree.

    Returns the worktree path. Does NOT mutate the main repo's HEAD.

    Mechanic: create a detached worktree at the target location, switch to an
    orphan branch inside it, clear the worktree, commit one empty commit.
    The main repo's working tree and HEAD are untouched throughout.
    """
    branch = f"orca-eval-state/{name}"
    worktree_path = repo_root / ".orca-state" / "eval-states" / name

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
                f"init: orca eval state for {name}",
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


def scaffold_eval(repo_root: Path, name: str) -> Path:
    """Create `.orca/evals/<name>/` with skeleton files. Returns the directory.

    Also creates `orca-eval-state/<name>` (orphan branch) and a persistent
    author worktree at `.orca-state/eval-states/<name>/`. The state_ref
    marker pointing at that branch is stamped into input.md.
    """
    if not _KEBAB_RE.match(name):
        msg = f"eval name must be kebab-case (lowercase + hyphens), got {name!r}"
        raise ValueError(msg)

    eval_dir = repo_root / ".orca" / "evals" / name
    if eval_dir.exists():
        msg = f"eval directory already exists: {eval_dir}"
        raise FileExistsError(msg)

    _create_state_branch_and_worktree(repo_root, name)

    eval_dir.mkdir(parents=True)
    input_text = _SKELETON_INPUT.replace("TODO_STATE_REF", f"orca-eval-state/{name}")
    (eval_dir / "eval-flow.yml").write_text(_SKELETON_EVAL_FLOW)
    (eval_dir / "input.md").write_text(input_text)
    (eval_dir / "assertions.md").write_text(_SKELETON_ASSERTIONS)
    return eval_dir


def list_evals(repo_root: Path) -> list[str]:
    """Return sorted list of eval names under .orca/evals/."""
    evals_dir = repo_root / ".orca" / "evals"
    if not evals_dir.is_dir():
        return []
    return sorted(d.name for d in evals_dir.iterdir() if d.is_dir() and (d / "eval-flow.yml").exists())


def resolve_eval_paths(repo_root: Path, name: str) -> EvalPaths:
    """Resolve the canonical files for an eval by name."""
    eval_dir = repo_root / ".orca" / "evals" / name
    config_path = eval_dir / "eval-flow.yml"
    if not config_path.exists():
        msg = f"eval '{name}' not found: {config_path} does not exist"
        raise FileNotFoundError(msg)
    task_file = eval_dir / "input.md"
    return EvalPaths(config_path=config_path.resolve(), task_file=task_file.resolve())


async def _submit_run(
    repo_root: Path,
    config_path: Path,
    task_file: Path,
    state_ref: str,
    max_hops: int = 10,
    max_retries: int = 2,
) -> str:
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
        "state_ref": state_ref,
        "max_hops": max_hops,
        "max_retries": max_retries,
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


def run_eval(repo_root: Path, name: str) -> str:
    """Submit an eval run to the daemon. Returns the run_id."""
    paths = resolve_eval_paths(repo_root, name)
    state_ref = parse_state_ref(paths.task_file)
    if state_ref is None:
        msg = (
            f"eval '{name}' has no state_ref in input.md frontmatter — add "
            f"`state_ref: orca-eval-state/{name}` and create the branch with "
            f"`orca eval add` (or fix the marker)."
        )
        raise RuntimeError(msg)
    return asyncio.run(_submit_run(repo_root, paths.config_path, paths.task_file, state_ref))


def eval_command(args: Namespace, root: Path | None = None) -> None:
    """Dispatch `orca eval` based on args.args and args.all."""
    from orca.cli.daemon_cmd import _repo_root

    repo = _repo_root(root)
    sub_args: list[str] = list(args.args)

    if args.all:
        names = list_evals(repo)
        if not names:
            print("No evals found under .orca/evals/.", file=sys.stderr)
            raise SystemExit(1)
        for name in names:
            try:
                run_id = run_eval(repo, name)
            except (FileNotFoundError, RuntimeError) as exc:
                print(f"{name}: error: {exc}", file=sys.stderr)
                continue
            print(f"{name}: started (run_id={run_id})")
        return

    if sub_args and sub_args[0] == "add":
        if len(sub_args) != 2:
            print("Usage: orca eval add <name>", file=sys.stderr)
            raise SystemExit(2)
        name = sub_args[1]
        try:
            path = scaffold_eval(repo, name)
        except (ValueError, FileExistsError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        wt = repo / ".orca-state" / "eval-states" / name
        print(f"Scaffolded: {path}")
        print(f"State branch: orca-eval-state/{name}")
        print(f"Author worktree: {wt}")
        print()
        print("Next:")
        print(f"  cd {wt}")
        print("  # arrange your eval state, then:")
        print('  git add . && git commit -m "seed: <describe scenario>"')
        print(f"  # then: orca eval {name}")
        return

    if sub_args:
        if len(sub_args) != 1:
            print("Usage: orca eval <name>", file=sys.stderr)
            raise SystemExit(2)
        try:
            run_id = run_eval(repo, sub_args[0])
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Run started: {run_id}")
        return

    names = list_evals(repo)
    if not names:
        print("No evals found under .orca/evals/.")
        return
    for name in names:
        print(name)
