---
name: orca-prompt-config-rewrite
description: Use when an orca run is paused in debug mode and the user has chosen "Modify prompt + config & restart". Reads inline comments left by the user and rewrites the state's prompt template and/or workflow config slice, then calls orca_restart_state to re-dispatch the worker. Triggers when an `orca-workflow-run` host loop detects a `debug_modify_request` event.
---

# orca-prompt-config-rewrite

This skill executes the **prompt + config rewrite** half of orca's debug-mode
review loop. The user has already paused the worker, reviewed the diff in the
browser, and clicked "Modify prompt + config & restart". The browser
dispatched the decision back to the daemon, which emitted a
`debug_modify_request` event. The host (your current session) is now invoking
this skill to perform the rewrite.

**Required reading:**
- The bundled playbook `orca-prompt-config-rewrite.md` (call
  `orca_get_playbook("orca-prompt-config-rewrite")`).

Follow the playbook procedure exactly: fetch snapshot, fetch comments, read
source files, compose edits via the `Edit` tool (user reviews inline),
validate YAML, call `orca_restart_state`.
