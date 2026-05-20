# Prompt Design

The conventions Orca uses to write a single state prompt that converges a worker on the output its assertions expect.

This is a reference, not a procedural playbook. It explains the conventions and pitfalls of prompt prose itself — *not* the assertions-first methodology that anchors it. For the methodology (why assertions exist, how to draft them, the iteration loop, failure attribution), see the companion [`assertions-design.md`](assertions-design.md). Read that first; this doc is the prompt-side counterpart.

> Audience: you, the agent. Not the user.

## 1. The problem prompts face

A modern Orca prompt is 200–500 lines of carefully-stacked instructions, variable references, and constraints. It is agent-authored — the user almost never writes a prompt from scratch, and rarely reads one end-to-end. So when output drifts, the natural human moves are unproductive: rewriting from scratch loses prior wins; pasting more details makes the prompt longer, more entangled, and more brittle. Prompts rot.

The cure is to design prompts against a fixed point they cannot drift away from. That fixed point is a user-curated `assertions.md` — see [`assertions-design.md`](assertions-design.md). A prompt's job is to make the worker emit output that passes the assertions. Everything below is about how to write the prompt prose so that it actually does.

## 2. Designing prompts for checkability

### Prefer structured `result_format` fields over free-form text

Enum outcomes beat free-form `status` strings. Lists of structured items beat markdown blob outputs. Named scalars (counts, ids, paths) beat `summary` fields. Every escape into prose is an escape from checkability.

Bad — a code-review state with everything buried in prose:

```yaml
result_format:
  outcome: { type: enum, values: [approve, request_changes] }
  summary: { type: string }
```

Every interesting criterion ("did the reviewer point at the SQL injection on line 42?", "did it flag more than one issue?", "are the messages actionable?") is unevaluable — the answers are buried in `summary`.

Good — the same state with findings promoted to a typed list:

```yaml
result_format:
  outcome:
    type: enum
    values: [approve, request_changes, blocked]
  findings:
    type: list
    items:
      file: { type: string }
      line: { type: integer }
      severity: { type: enum, values: [critical, major, minor] }
      message: { type: string }
    required_when: [request_changes]
```

Now criteria can count findings, check that some finding points at the expected file:line, validate severity, regex-check messages, and detect duplicates.

### State constraints explicitly in prose

A constraint stated only in the prompt is hope; a constraint also checked by an assertion is verifiable (see [`assertions-design.md`](assertions-design.md) §4). The prompt's job is to **still state the constraint clearly** so the worker has a chance of obeying it. Example:

> "ONLY modify files under `issue.fields.scope_boundary`. Do not edit anything outside this prefix."

Phrase constraints near the end of the prompt where the worker's attention is freshest. One sentence per constraint; no qualifiers, no examples-of-examples.

## 3. Iterating on a prompt

When a test reports a failed criterion, walk the failure-attribution taxonomy in [`assertions-design.md`](assertions-design.md) §5 **before** editing the prompt. Only one of the six failure modes is a prompt bug. Editing the prompt without attributing first is the rot.

When the attribution does point at the prompt:

### Minimal-edit discipline

The edit is the *minimum* needed to make the failing criterion pass. Not a broad rewrite. Resist "while we're at it" — that is the rot speaking.

- One failing criterion → one targeted change (one sentence in the prompt, one field in the schema, one line in `assertions.md`).
- Group cleanups happen on their own pass with their own test runs, not bundled with a fix.

### Model and flow swaps are not exceptions

Every change is validated by the same loop. Model swaps (`claude-code` vs `codex` vs `opencode`), `max_hops` adjustments, prompt rewrites, schema changes — none have a "just edit and ship" path. Run the test.

## 4. Anti-patterns

- **Editing the prompt before reading the report.** The fix presumes a cause; the report names the cause. See [`assertions-design.md`](assertions-design.md) §5 for the failure-attribution taxonomy.
- **"While we're at it" prompt edits.** Each edit fixes one failing criterion. Cleanups happen on their own pass.

## Cross-references

- [`assertions-design.md`](assertions-design.md) — the assertions-first methodology, anatomy of an assertion, iteration loop, failure attribution, drift discipline. Read this *first*.
- [`orca-prompt-create.md`](../orca-prompt-create.md) — mechanics of writing a single state prompt (template variables, structure, pitfalls).
- [`orca-test-create.md`](../orca-test-create.md) — interactive procedure for authoring a test that grades a prompt.
- [`orca-config-reference.md`](orca-config-reference.md) — full schema reference, including `result_format` field types.
- [`orca-workflow-patterns.md`](orca-workflow-patterns.md) — reusable building blocks for workflows.
