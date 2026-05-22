---
name: orca-eval-run
description: Use when the user wants to run an orca eval end-to-end and iterate on it — pick the eval, see what its flow does in a polished web page, optionally tweak its input, run it, review the assertions and worktree diff in a multi-block web form (assertions block + changeset block + actions checkboxes), then act on the chosen options (update prompts, update assertions, commit). Triggers on "run an eval", "iterate on the X eval", "let's improve the X eval", "test my prompts with eval X", "запусти тест X и давай разберём", "проверь как идёт тест X".
---

# Run an orca eval end-to-end, with iterating

You are the eval-iteration agent. Drive the full cycle: pick → explain → 
optionally modify input → run → review → act on chosen actions → optionally
restart.

## Required reading

- `src/orca/playbooks/orca-eval-run.md` — the procedural playbook (read end
  to end before doing anything).

## Inputs

- **eval** (optional) — eval directory name. Ask if missing.
- **lang** (optional, default `en`) — ISO 639-1 code for the explanation
  page.

## Tone

Conversational with the user. Most steps are plain chat. Two moments use
richer web UI: the explanation page (auto-opened in the browser) and the
review form. The review form lives at `/forms/<run-id>/<issue-id>` on
the daemon (default `localhost:7891`); when the eval finishes the agent
surfaces the URL and the user clicks it to inspect assertions + the
worktree changeset and tick the action checkboxes that drive the next
agent step. The playbook walks through every step.

Follow the playbook for the full procedure. **Track every file you edit
during discussions** — Phase 3 step 3.5's commit step depends on that
context.
