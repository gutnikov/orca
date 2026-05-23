# orca-prompt-config-rewrite

> Rewrite a state's prompt template and/or workflow config slice from user
> review comments collected during a debug pause.

## Inputs

- `run_id` (string) — orca run identifier.
- `issue_id` (string) — the paused issue's ID.

## Steps

1. **Fetch the review snapshot.** Call
   `orca_get_debug_review(root, run_id, issue_id)`.
   - If the response has `"error": "not_pending"`, the issue is no longer
     paused — report this to the user and stop.

2. **Fetch the user's comments.** Call
   `orca_get_issue(root, run_id, issue_id)` and scan its `event_log` in
   reverse for the most recent entry with `type == "debug_modify_request"`.
   Extract `data.comments` — each comment is `{file, line, body}`.

3. **Read the source files the comments target.**
   - Comments anchored to `prompt.md` → read `.orca/prompts/<state>.md`. The
     state name is `issue.state` from the same `orca_get_issue` response.
   - Comments anchored to `flow.yml::<state>` → read `.orca/<workflow>.yml`.
     The slice in the snapshot is just for readback; the edit target is the
     full file.
   - Comments anchored to `result.json` or to changeset files → context only.
     Do NOT modify result.json or worker-produced code.

4. **Compose targeted edits.**
   - Prompt comments: rewrite the relevant sections of
     `.orca/prompts/<state>.md` to address the feedback. Preserve template
     variables (`{{...}}`) and unrelated content.
   - Config comments: edit `.orca/<workflow>.yml` in the relevant state
     block. Common edits: `model:`, `kind:`, `prompt:`, `timeout:`,
     `progress:`. Do NOT change the state graph (`on:` rules) unless
     explicitly requested.
   - Show edits via the standard `Edit` tool so the user reviews and approves
     inline.

5. **Verify the workflow YAML still parses.** Read the rewritten YAML and
   confirm it loads. If not, ask the user to confirm or revert.

6. **Restart the state.** Call
   `orca_restart_state(root, run_id, issue_id)`.
   - On success: the daemon resets the worktree and re-dispatches the worker
     with the new prompt. Report success.
   - On failure (e.g., config still invalid): surface the error. The issue
     remains in `modify_pending` — user can iterate or pick another action
     in the browser.

## What this skill does NOT do

- Modify the state graph. Graph changes go through `orca-workflow-create`.
- Write commits.
- Apply edits without user approval — always via `Edit`/`Write`.
