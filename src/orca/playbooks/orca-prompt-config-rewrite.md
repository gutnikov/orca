# orca-prompt-config-rewrite

> Rewrite a state's prompt template and/or workflow config slice from user
> review comments collected during a debug pause.

## Inputs

- `run_id` (string) — orca run identifier.
- `issue_id` (string) — the paused issue's ID.

## Steps

1. **Determine the variant** (restart vs continue). Call
   `orca_get_issue(root, run_id, issue_id)` and scan its `event_log` in
   reverse for the most recent entry with `type == "debug_decision"`.
   - `data.action == "modify_restart"` → user picked
     **Modify prompts & configs → restart step**. After rewriting, finish
     with `orca_restart_state` (resets worktree + re-dispatches worker).
   - `data.action == "modify_continue"` → user picked
     **Modify prompts & configs → continue**. The state has already
     advanced — finish with `orca_clear_modify_pending` (no re-dispatch).
   The variant only affects the *final* call in step 6; the rewrite itself
   is identical.

2. **Fetch the review snapshot.** Call
   `orca_get_debug_review(root, run_id, issue_id)`.
   - On the `modify_restart` path: if the response has `"error": "not_pending"`,
     the issue is no longer paused — report this to the user and stop.
   - On the `modify_continue` path: the snapshot endpoint returns
     `not_pending` (because `debug_pending` was cleared on accept). Read the
     comments from the same `debug_modify_request` event in step 3 instead.

3. **Fetch the user's comments.** Scan the `event_log` from step 1 in
   reverse for the most recent entry with `type == "debug_modify_request"`.
   Extract `data.comments` — each comment has shape
   `{id, file, line, body, thread_messages}` where `thread_messages` is a
   list of `{role: "user"|"agent", body: str}` entries representing the
   in-review dialogue. Empty list (or missing field, on pre-0.7.0 daemons)
   means no agent interaction happened. The original comment `body` is the
   user's first message; `thread_messages` entries are subsequent turns.
   Read the WHOLE thread — the final user intent often emerges over
   multiple turns rather than in the original `body` alone.

3. **Read the source files the comments target.**
   - Comments anchored to `prompt.md` → read `.orca/prompts/<state>.md`. The
     state name is `issue.state` from the same `orca_get_issue` response.
   - Comments anchored to `flow.yml::<state>` → read `.orca/<workflow>.yml`.
     The slice in the snapshot is just for readback; the edit target is the
     full file.
   - Comments anchored to `result.json` or to changeset files → context only.
     Do NOT modify result.json or worker-produced code.
   - Comments with `file == "__overall__"` and `line == null` → **free-form
     overall feedback** left in the web UI's "Overall feedback" textarea.
     Treat as general direction/intent that applies to the rewrite as a
     whole: decide which file(s) it implies edits to and fold it into the
     same edit pass as the line-anchored comments. Surface this to the user
     in the CLI before composing edits so they can sanity-check your reading
     of it.

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

6. **Finish based on the variant from step 1.**
   - `modify_restart` → call `orca_restart_state(root, run_id, issue_id)`.
     On success the daemon resets the worktree and re-dispatches the worker
     with the new prompt. Report success.
   - `modify_continue` → call
     `orca_clear_modify_pending(root, run_id, issue_id)`. The state has
     already advanced (the user accepted the worker's output at decide
     time); this just drops the flag so the polling loop stops seeing
     pending work. Report success.
   - On failure of either call (e.g., config still invalid for
     `restart`): surface the error. The issue remains in `modify_pending`
     — user can iterate or pick another action in the browser.

## What this skill does NOT do

- Modify the state graph. Graph changes go through `orca-workflow-create`.
- Write commits.
- Apply edits without user approval — always via `Edit`/`Write`.
