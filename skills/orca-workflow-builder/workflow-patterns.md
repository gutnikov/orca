# Workflow Patterns

Reusable building blocks for orca workflows. Compose these into complete workflows. Each pattern shows when to use it, a config snippet, and notes.

Also read `example/orca.yml` and `example/prompts/` in the orca repo for a complete real-world workflow.

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
            then: done
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
              values: [done, blocked, needs_feedback]
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
              values: [applied, failed]
        on:
          applied: done
          failed: implementing
```

**Notes:**
- Epic scoping creates child tasks with clear scope boundaries
- Tasks run in parallel (no max_workers on implementing)
- Applying serialized with `max_workers: 1` to prevent merge conflicts
- Epic auto-unblocks when all tasks reach `done`

## Serialized Merge

**When:** A state where only one worker should run at a time (merging, deploying, writing to shared resource).

```yaml
applying:
  max_workers: 1
  worker:
    kind: claude-code
    prompt: prompts/applying.md
    timeout: 600
    result_format:
      outcome:
        type: enum
        values: [applied, conflict]
  on:
    applied: done
    conflict: implementing
```

**Notes:**
- `max_workers: 1` queues issues — next pops when current finishes
- Limit is per (type, state) pair — different types have separate queues
- Set a reasonable `timeout` since queued issues wait

## Retry Loop with Escalation

**When:** Work might fail and should be retried with context about the failure.

```yaml
max_worker_retries: 3

states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [done, blocked, needs_feedback]
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
- `max_worker_retries` bounds total failures (prevents infinite loops)
- Worker failures (crashes/timeouts) also count toward the limit
- `needs_feedback` pauses for user input, then re-dispatches

## Feedback Loop

**When:** Worker might need human clarification mid-workflow.

```yaml
implementing:
  worker:
    kind: claude-code
    prompt: prompts/implementing.md
    result_format:
      outcome:
        type: enum
        values: [done, blocked, needs_feedback]
        values_description:
          needs_feedback: "Need user clarification before proceeding"
  on:
    done: done
    blocked: implementing
    # needs_feedback has no on: rule — orchestrator handles it
```

**Notes:**
- `needs_feedback` is reserved — no `on:` rule needed
- Orchestrator spawns Slack feedback agent automatically
- After user answers, worker re-dispatches with `{{ issue.feedback_context }}`
- Define `feedback_questions` and `feedback_context` fields if prompts reference them
- Requires Slack integration configured at top level

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
            then: done
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
            then: done
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
- Parent blocks until all children reach `done` (cascading unblock)
- Sub-issues can have `depends_on` keys for ordering within a type

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
- Issue is advanced manually (via API, TUI, or CLI)
- Use for: code review gates, deployment approval, manual QA sign-off
- Passive states are exempt from the "unreachable states" validation (they can be targets of on: rules)

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
- Use `max_hops` to bound the cycle (e.g. 10 hops prevents infinite back-and-forth)
- Review worker should produce specific, actionable feedback (not just "needs work")
- Implementing worker should reference `{{ issue.event_log }}` to see previous review feedback
