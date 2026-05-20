# Assertions: scoping-decomposes-large-spec

A refactor spec that covers two unrelated subsystems (auth and payments)
should be decomposed into sub-issues, not passed through as-is. The criteria
below grade the scoping state's `result.json` and the surrounding worktree.

## Criteria

### outcome-is-decompose
The scoping state's result `outcome` is `decompose` (not `ready`). The whole
test premise is that a multi-subsystem refactor should not flow straight into
planning.

### produces-multiple-sub-issues
The `sub_issues` field in the scoping result contains at least 2 entries. One
entry per subsystem is the floor; finer-grained splits are fine.

### sub-issues-cover-original-scope
Across all sub_issues, the union of `scope_boundary` paths covers every
file or directory mentioned in the input description. Specifically, both
`src/auth/` and `src/payments/` must appear in at least one sub-issue's
`scope_boundary`.

### sub-issues-are-non-overlapping
No two sub_issues share a path component in their `scope_boundary`. Each
sub-issue owns its files exclusively so independent workers cannot collide
on a merge.

### titles-are-actionable
Every sub-issue `title` reads as an imperative action (e.g. "Split session
handling into its own module"), not a bare noun phrase ("Authentication").
Titles drive a human reader's understanding of what each follow-up ticket
will do.
