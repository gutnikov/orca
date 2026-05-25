# Run Retrospective

Write a retrospective for this workflow run. Analyze what happened across all stages
and produce `retro.md` in the repository root.

## Issue

**{{ issue.fields.title }}**

{{ issue.fields.description }}

## Run Context

- **Branch:** {{ run.branch }}
- **Workflow:** {{ run.workflow }}
- **Total duration:** {{ run.summary.total_duration }}
- **States visited:** {{ run.summary.states_visited | join(" → ") }}

## Session Logs

Read these to understand what each worker actually did:

{% for s in run.sessions %}
- **{{ s.state }}** ({{ s.outcome }}, {{ s.duration }}): `{{ s.log }}`
{% endfor %}

## Additional Files

- Structured event log (JSONL): `{{ run.log }}`
- State snapshot (JSON): `{{ run.state }}`

### File Formats
{% for name, desc in run.formats.items() %}
- **{{ name }}**: {{ desc }}
{% endfor %}

{% if run.summary.failures %}
## Failures During This Run

{% for state, reason in run.summary.failures.items() %}
- **{{ state }}**: {{ reason }}
{% endfor %}
{% endif %}

## Your Task

1. Read the session logs for each completed stage
2. Write `retro.md` covering:
   - **Timeline** — what happened in each stage, how long it took
   - **What went well** — stages that completed smoothly
   - **What went wrong** — failures, retries, wasted time
   - **Recommendations** — concrete suggestions for improving the workflow or prompts
3. Commit `retro.md` to the repository
