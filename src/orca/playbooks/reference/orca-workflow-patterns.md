# Orca Workflow Patterns

Reusable building blocks for orca workflows. Compose these into complete workflows. Each pattern shows when to use it, a config snippet, and notes.

For a complete worked example combining several of these patterns, fetch `examples/project/orca.yml` and `examples/project/prompts/` from the orca repo at https://github.com/gutnikov/orca/tree/main/examples/project.

For schema-level details on any field shown below, see [`orca-config-reference.md`](orca-config-reference.md). For term definitions (`outcome` vs `target`, `blocked` vs `failed` vs `waiting`, etc.), see [`orca-glossary.md`](orca-glossary.md).

## Sequential Pipeline

**When:** Simple linear flow — one issue progresses through stages.

```yaml
initial: planning
states:
  planning:
    worker:
      kind: claude-code
      prompt: prompts/planning.md
      result_format:
        outcome:
          type: enum
          values: [ready, blocked]
    on:
      ready: implementing
      blocked: planning
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [done, blocked]
    on:
      done: done
      blocked: planning
```

**Notes:**
- Each state has one clear job
- `blocked` loops back for human intervention or retry
- Add more states in the middle as needed (testing, review, applying)

## Decompose + Parallel Execution

**When:** Large task needs to be broken into independent sub-tasks that run in parallel.

```yaml
root_type: epic
types:
  epic:
    fields:
      title: { type: string, description: "Epic title" }
      description: { type: string, description: "What to build" }
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scoping.md
          result_format:
            outcome:
              type: enum
              values: [decompose, ready]
              values_description:
                decompose: "Break into sub-tasks"
                ready: "Small enough to implement directly"
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
        on:
          decompose:
            action: decompose
            child_type: task
          ready: done
  task:
    fields:
      title: { type: string, description: "Task title" }
      scope_boundary: { type: string, description: "Files this task owns" }
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/implementing.md
          result_format:
            outcome:
              type: enum
              values: [done, blocked]
        on:
          done: applying
          blocked: implementing
      applying:
        max_workers: 1
        worker:
          kind: claude-code
          prompt: prompts/applying.md
          result_format:
            outcome:
              type: enum
              values: [applied, conflict]   # use a domain-specific name; avoid `failed`
        on:                                  # to keep it visibly distinct from the built-in
          applied: done                      # `failed` target (which triggers retry semantics)
          conflict: implementing
```

**Notes:**
- Epic scoping creates child tasks with clear scope boundaries
- Tasks run in parallel (no `max_workers` on implementing)
- Applying serialized with `max_workers: 1` to prevent merge conflicts
- Epic stays blocked after decomposition and auto-unblocks when all tasks reach `done`
- `conflict` here is a user-defined outcome value, not the built-in `failed` target. If you want a conflict to count toward worker-failure retries (and stop after `max_worker_retries`), route it to `failed` instead of `implementing`. See *Built-in Transition Targets* in `orca-config-reference.md`.

## Serialized Merge

**When:** A state where only one worker should run at a time (merging, deploying, writing to shared resource).

```yaml
applying:
  max_workers: 1
  worker:
    kind: claude-code
    prompt: prompts/applying.md
    inactivity_timeout: 600
    result_format:
      outcome:
        type: enum
        values: [applied, conflict]
  on:
    applied: done
    conflict: implementing                 # or `failed` to trigger retry semantics
```

**Notes:**
- `max_workers: 1` queues issues — next pops when current finishes
- Limit is per (type, state) pair — different types have separate queues
- Set a reasonable `inactivity_timeout` for the apply work itself. Queued issues have not started their worker yet, so they do not consume worker inactivity time.

## Retry Loop with Escalation

**When:** Work might fail and should be retried with context about the failure.

```yaml
states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [done, blocked]
        blockers:
          type: string
          description: "What's blocking progress"
          required_when: [blocked]
    on:
      done: done
      blocked: implementing
```

**Notes:**
- `blocked` loops back to same state — worker gets another attempt
- Define `failure_context` field so prompts can reference why previous attempt failed
- `max_worker_retries` bounds total crash retries (prevents infinite loops). Set it at launch (`orca run --max-retries 3`); current workflow YAML does not apply it.
- Worker failures (crashes/timeouts) also count toward the limit
- Workers can write `{"outcome": "waiting"}` to pause for human input without consuming a retry

## Human-in-the-Loop (Waiting)

**When:** Worker might need human input mid-session — a PR to be merged, a question answered, a deploy to complete.

```yaml
implementing:
  worker:
    kind: claude-code
    prompt: prompts/implementing.md
    inactivity_timeout: 3600   # active-work no-progress timeout; paused while waiting
    result_format:
      outcome:
        type: enum
        values: [done, blocked]
        values_description:
          done: "All changes committed, tests pass"
          blocked: "Cannot proceed — explain in summary"
      summary:
        type: string
        description: "What was done or what's blocking"
  on:
    done: done
    blocked: implementing
```

**Notes:**
- `waiting` is a built-in outcome — no `on:` rule needed, not declared in `result_format`
- Worker writes `{"outcome": "waiting", "reason": "need PR #42 merged"}` to pause
- Orchestrator keeps the tmux session alive and pauses the inactivity timer
- Unblock via CLI: `orca unblock <run_id> <issue_id> -m "PR merged, continue"`
- The message is injected into the live session via `tmux send-keys`
- Workers can block and unblock multiple times in a single session
- Instruct workers in the prompt to use `waiting` when they need external action

## Multi-Type Hierarchy

**When:** Different kinds of work follow different workflows (e.g. epic → story → task).

```yaml
root_type: epic
types:
  epic:
    fields:
      title: { type: string }
    initial: planning
    states:
      planning:
        worker:
          kind: claude-code
          prompt: prompts/plan_epic.md
          result_format:
            outcome:
              type: enum
              values: [decompose]
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
        on:
          decompose:
            action: decompose
            child_type: story
  story:
    fields:
      title: { type: string }
      scope_boundary: { type: string }
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/impl_story.md
          result_format:
            outcome:
              type: enum
              values: [done, decompose]
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
        on:
          done: done
          decompose:
            action: decompose
            child_type: task
  task:
    fields:
      title: { type: string }
      scope_boundary: { type: string }
    initial: coding
    states:
      coding:
        worker:
          kind: claude-code
          prompt: prompts/code_task.md
          result_format:
            outcome:
              type: enum
              values: [done, blocked]
        on:
          done: done
          blocked: coding
```

**Notes:**
- Each type has its own state machine — epic plans, story implements or decomposes further, task codes
- `child_type` controls what type decomposed issues become
- Parent issues block after decomposition until all children reach `done` (cascading unblock). Add `then:` only for deliberate fire-and-forget decomposition; if the root issue reaches `done`, the run loop terminates.
- Sub-issues can have `depends_on` lists of sibling `key` values for ordering within a type

## Gate State

**When:** Workflow needs a human approval point or manual trigger before proceeding.

```yaml
states:
  review:
    # No worker, no on: rules — passive state
    # Issue waits here until manually advanced via AdvanceEvent
  deploying:
    worker: { ... }
    on:
      done: done
```

**Notes:**
- Passive states have no worker and no `on:` rules
- Issue is advanced manually (via API or TUI)
- Use for: code review gates, deployment approval, manual QA sign-off
- Passive states are exempt from the "unreachable states" validation (they can be targets of on: rules)

## Failure-Context Propagation

**When:** A state should retry with awareness of what went wrong last time — typing errors, test failures, lint output.

```yaml
types:
  task:
    fields:
      title: { type: string }
      scope_boundary: { type: string }
      failure_context:                   # auto-populated by orca
        type: string
        description: "Error message from the last failure (set by the orchestrator)"
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/implementing.md
          result_format:
            outcome:
              type: enum
              values: [done, blocked]
        on:
          done: done
          blocked: implementing
```

In `prompts/implementing.md`:

```jinja2
{% if issue.fields.failure_context %}
## Previous attempt failed with:

{{ issue.fields.failure_context }}

Read this carefully — don't repeat the same mistake.
{% endif %}
```

**Notes:**
- `failure_context` is set by the orchestrator on worker failure or when targeting the built-in `failed` state — see *Auto-Populated Fields* in `orca-config-reference.md`.
- Declare it in `fields:` only so prompts can reference it via Jinja; you don't write to it.
- Combine with a launch-time `max_worker_retries` limit to bound how long this retry loop runs.

## Dependency-Ordered Sub-Issues

**When:** Decomposition produces sub-issues that must run in a specific order — e.g., a database migration before the code that uses it.

The decomposing prompt emits each child issue with a stable `key`; `depends_on` references those keys. Orca resolves keys to real issue ids when it creates the child issues:

```json
{
  "outcome": "decompose",
  "sub_issues": [
    {
      "key": "001-migration",
      "fields": { "title": "Add column", "scope_boundary": "migrations/" }
    },
    {
      "key": "002-code",
      "fields": { "title": "Use column", "scope_boundary": "src/users/" },
      "depends_on": ["001-migration"]
    }
  ]
}
```

**Notes:**
- An issue with `depends_on` waits until every listed issue reaches `done` before its initial state runs.
- Within a type, `depends_on` is the only ordering mechanism — sibling issues without dependencies run in parallel up to `max_workers`.
- A prompt that needs to know its predecessors can read `{{ issue.depends_on }}` and `{{ issue.event_log }}`.
- If the parent decomposer can't guarantee non-overlapping `scope_boundary` between children, dependency-order them so they don't stomp on each other.

## Iterative Refinement

**When:** Work goes through review cycles — implement, review, rework until approved.

```yaml
states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [ready_for_review, blocked]
    on:
      ready_for_review: reviewing
      blocked: implementing
  reviewing:
    worker:
      kind: claude-code
      prompt: prompts/reviewing.md
      result_format:
        outcome:
          type: enum
          values: [approved, needs_rework]
    on:
      approved: done
      needs_rework: implementing
```

**Notes:**
- `needs_rework` loops back to implementing with review feedback
- Use a launch-time `max_hops` limit to bound the cycle (e.g. 10 hops prevents infinite back-and-forth)
- Review worker should produce specific, actionable feedback (not just "needs work")
- Implementing worker should reference `{{ issue.event_log }}` to see previous review feedback
