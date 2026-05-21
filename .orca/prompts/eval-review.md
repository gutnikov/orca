You are running the `review` step of the `eval-review` flow.

Your job: read the eval's results and the worktree diff, present them to the
user via a web form, and write back the user's review comments and chosen
actions. The playbook orchestrator reads the result file when you finish.

Write all intermediate and final results to `{{ result_path }}`. The
orchestrator polls this file and parses it as JSON every poll.

## Inputs (from `{{ issue.fields }}`)

- `eval` — the eval directory name (under `.orca/evals/`)
- `run_id` — the run identifier; the worker output is at
  `.orca-state/eval-states/{{ issue.fields.eval }}/{{ issue.fields.run_id }}/`

## Step 1 — read the report

Read `.orca-state/eval-states/{{ issue.fields.eval }}/{{ issue.fields.run_id }}/report.md`.

The report's format varies by `assert` state implementation; the common
shape is a markdown document with a section per criterion containing a
status ("passed"/"failed"/"skipped"), the criterion's name, and the assert
state's reasoning. Parse it into a list of objects:

```json
[
  { "name": "criterion_a", "status": "passed", "summary": "<one-line>", "detail": "<markdown body or omit>" },
  { "name": "criterion_b", "status": "failed", "summary": "...", "detail": "..." }
]
```

If `report.md` is missing or unparseable, emit an empty array — the form will
still render with a markdown block explaining the issue.

## Step 2 — compute the worktree diff

From the worker's worktree (`.orca-state/eval-states/{{ issue.fields.eval }}/{{ issue.fields.run_id }}/`),
compute the diff against the state branch:

```
git -C .orca-state/eval-states/{{ issue.fields.eval }}/{{ issue.fields.run_id }} diff orca-eval-state/{{ issue.fields.eval }}..HEAD
```

Parse the output per file into a `ChangesetFile` object as defined by the
`changeset` form block (see `web/src/lib/schema.ts`):

```json
{
  "path": "src/foo.py",
  "status": "modified",
  "language": "python",
  "additions": 12,
  "deletions": 3,
  "diff": "<unified diff for this file, hunks only>"
}
```

`status` is one of `"added" | "modified" | "deleted" | "renamed"`.

If there is no diff (worker made no changes), emit an empty `files` array;
the changeset block will render a "no changes" placeholder.

## Step 3 — emit the waiting form

Write to `{{ result_path }}`:

```json
{
  "outcome": "waiting",
  "reason": "Review eval results",
  "form": {
    "title": "Review eval results",
    "description": "{{ issue.fields.eval }} finished. Review the assertions, the worktree diff, and pick what to do next.",
    "submit_label": "Apply",
    "cancel_label": "Skip",
    "steps": [
      {
        "blocks": [
          {
            "kind": "markdown",
            "content": "## Summary\n\n<one-paragraph plain-language summary of the results — e.g. 'X of Y criteria passed; the worktree changed Z files'>"
          },
          {
            "kind": "assertions",
            "criteria": [/* from Step 1 */]
          },
          {
            "kind": "changeset",
            "name": "diff_review",
            "files": [/* from Step 2 */]
          },
          {
            "kind": "field",
            "name": "update_prompts",
            "type": "checkbox",
            "label": "Update prompts to address failed assertions",
            "default": false
          },
          {
            "kind": "field",
            "name": "update_assertions",
            "type": "checkbox",
            "label": "Update assertions based on review comments",
            "default": false
          },
          {
            "kind": "field",
            "name": "commit",
            "type": "checkbox",
            "label": "Commit changes",
            "default": false
          }
        ]
      }
    ]
  }
}
```

After writing, the orchestrator pauses your session until the user submits
or cancels the form.

## Step 4 — write the final outcome on resume

When the resume envelope arrives:

- **Submit envelope** `{"submitted": true, "values": { "diff_review": [...], "update_prompts": <bool>, "update_assertions": <bool>, "commit": <bool> }}`:

  ```json
  {
    "outcome": "done",
    "cancelled": false,
    "diff_review": <values.diff_review>,
    "update_prompts": <values.update_prompts>,
    "update_assertions": <values.update_assertions>,
    "commit": <values.commit>
  }
  ```

- **Cancel envelope** `{"submitted": false, "cancelled": true}`:

  ```json
  {"outcome": "done", "cancelled": true, "update_prompts": false, "update_assertions": false, "commit": false}
  ```

Write to `{{ result_path }}` and stop. Acting on the chosen options is the
playbook's job, not yours.
