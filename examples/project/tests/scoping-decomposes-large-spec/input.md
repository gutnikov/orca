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
state_ref: orca-test-state/scoping-decomposes-large-spec
---

# Scenario

This test exercises the `scoping` state with a deliberately broad refactor
spec that spans two unrelated subsystems. The scoping agent should recognise
the smell and decompose the issue into at least one sub-issue per subsystem,
each with a non-overlapping `scope_boundary`.

The worktree is checked out from `orca-test-state/scoping-decomposes-large-spec`,
which carries the two tangled legacy modules at `src/auth/legacy_auth.py`
and `src/payments/legacy_payments.py`. Edit that state under
`.orca-state/test-states/scoping-decomposes-large-spec/` and commit with
plain git when iterating.
