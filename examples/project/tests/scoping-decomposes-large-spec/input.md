---
title: "Refactor authentication and payments subsystems"
description: |
  Our `src/auth/` module has grown into a tangled mix of session handling,
  password hashing, and OAuth token exchange — three responsibilities that
  should live behind their own interfaces. Separately, `src/payments/` co-locates
  a Stripe-like API client, a refund flow, and a tiny JSON-file ledger; the
  ledger has nothing to do with the payments gateway and routinely causes
  unrelated diffs to collide.

  Split each of these modules along its natural seams. The auth refactor and
  the payments refactor share no files — they are two unrelated stories that
  happened to land in the same ticket.
scope_boundary: "src/auth/, src/payments/"
---

# Scenario

This test exercises the `scoping` state with a deliberately broad refactor
spec that spans two unrelated subsystems. The scoping agent should recognise
the smell and decompose the issue into at least one sub-issue per subsystem,
each with a non-overlapping `scope_boundary`.

## Setup instructions

The setup state should arrange the worktree to match the scenario:

1. Copy `tests/{{ run.test_name }}/fixtures/legacy-auth.py` to `src/auth/legacy_auth.py`
   (creating `src/auth/` if it does not exist).
2. Copy `tests/{{ run.test_name }}/fixtures/legacy-payments.py` to
   `src/payments/legacy_payments.py` (creating `src/payments/` if it does not exist).
3. Emit the issue fields (`title`, `description`, `scope_boundary`) from the
   frontmatter above — the scoping state needs them verbatim.

After setup, the worktree contains two tangled legacy modules and the scoping
agent has the issue context it needs to decide whether to decompose.
