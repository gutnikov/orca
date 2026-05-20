You are running the "select an eval" step of the `run-evals` flow.

Write all intermediate and final results to `{{ result_path }}`. The orchestrator polls this file and parses it as JSON every poll.

## Step 1 — scan `.orca/evals/`

Use the `ls` / file-list tools available to you. Treat **only immediate subdirectories** as candidates. Ignore files. Ignore hidden directories that begin with `.`.

- If the directory does not exist OR contains no subdirectories: write the final outcome immediately and stop:

  ```json
  {"outcome": "done", "selected": "none"}
  ```

- Otherwise, continue to Step 2.

## Step 2 — emit a waiting outcome with a form

Write a JSON document to `{{ result_path }}` of this exact shape, substituting the discovered subdirectory names for `<dirN>`:

```json
{
  "outcome": "waiting",
  "reason": "Pick which eval to run",
  "form": {
    "title": "Run an eval",
    "description": "Select one of the evals discovered under .orca/evals/.",
    "submit_label": "Run selected",
    "cancel_label": "Cancel",
    "steps": [
      {
        "blocks": [
          {"kind": "markdown", "content": "These are the eval directories discovered under `.orca/evals/`. Pick one."},
          {
            "kind": "field",
            "name": "eval",
            "type": "select",
            "label": "Eval",
            "required": true,
            "options": [
              {"value": "<dir1>", "label": "<dir1>"},
              {"value": "<dir2>", "label": "<dir2>"}
            ]
          }
        ]
      }
    ]
  }
}
```

After you write this file, **the orchestrator will pause your session** until the user submits the web form. You will then receive a single text message of the shape:

- on submit:   `{"submitted": true, "values": {"eval": "<picked>"}}`
- on cancel:   `{"submitted": false, "cancelled": true}`

Do not write any output before that message arrives. Do not run any other commands while waiting.

## Step 3 — write the final outcome

Once you receive the resume message:

- If it is the **submit** envelope, write:

  ```json
  {"outcome": "done", "selected": "<the picked value, verbatim>"}
  ```

- If it is the **cancel** envelope, write:

  ```json
  {"outcome": "done", "selected": "cancelled"}
  ```

Write the JSON to `{{ result_path }}` and then stop. Do not perform any other action — running the chosen eval is **not** part of this step.
