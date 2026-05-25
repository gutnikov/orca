---
name: orca-prompt-config-rewrite
description: Use when an orca run is paused in debug mode and the user has chosen either "Modify prompts & configs → restart step" or "Modify prompts & configs → continue". Reads inline comments left by the user and rewrites the state's prompt template and/or workflow config slice, then either calls orca_restart_state (restart variant) or orca_clear_modify_pending (continue variant). Triggers when an `orca-workflow-run` host loop detects modify_pending=true on an issue.
---

# orca-prompt-config-rewrite

This skill executes the **prompt + config rewrite** half of orca's debug-mode
review loop. The user has already paused the worker, reviewed the diff in the
browser, and clicked one of:

- **Modify prompts & configs → restart step** (action `modify_restart`) — state does NOT advance, worker is re-dispatched after the rewrite.
- **Modify prompts & configs → continue** (action `modify_continue`) — state DID advance (accept logic applied alongside), no re-dispatch.

Either way the daemon set `modify_pending=true` on the issue. The host (your
current session) is now invoking this skill to perform the rewrite.

**Required reading:**
- The bundled playbook `orca-prompt-config-rewrite.md` (call
  `orca_get_playbook("orca-prompt-config-rewrite")`).

Follow the playbook procedure exactly: read the latest `debug_decision`
event to pick the variant, fetch snapshot + comments, read source files,
compose edits via the `Edit` tool (user reviews inline), validate YAML, and
finish with the matching call — `orca_restart_state` for `modify_restart`,
`orca_clear_modify_pending` for `modify_continue`.

Each comment may carry `thread_messages`: a list of `{role, body}` entries
from the user↔agent dialogue that happened during the review. When present,
read the WHOLE thread — the final user intent often emerges over multiple
turns, and the original `body` is just the first message. If
`thread_messages` is empty or absent, treat the comment as a single message
(pre-0.7.0 shape).
