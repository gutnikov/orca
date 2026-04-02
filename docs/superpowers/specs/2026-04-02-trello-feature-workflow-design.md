# Trello Clone V2: Feature Delivery Workflow

## Overview

An orca workflow that takes a high-level, non-technical feature request from a stakeholder (e.g., "I want to see an empty board") and delivers a fully implemented, tested, Docker-deployed vertical slice — with stakeholder approval gates at key milestones.

**Target project:** `/Users/agutnikov/work/trello-clone-v2`
**Tech stack:** FastAPI + SQLAlchemy (backend), TanStack Start + shadcn/ui (frontend), PostgreSQL, Docker Compose
**Workflow file:** `orca.feature.yml` in the trello-clone-v2 repo root
**Prompts directory:** `prompts/` in the trello-clone-v2 repo root

## Input

A task file with two fields:

```yaml
title: "Empty board view"
description: "I want to see an empty board when I first open the app"
```

The description is a raw, non-technical stakeholder ask. No user stories, no acceptance criteria, no technical details.

## State Machine

```
refine → preview → plan → implement → verify → deploy → demo → done
  ↻          ↻                 ↻          ↻        ↻        ↻→implement
(slack)    (slack)          (slack)   (→implement) (retry)   (slack)
```

### Global Config

- `max_hops: 25` — enough for several feedback + fix loops
- `max_worker_retries: 5` — per-issue failure retry cap
- `base_branch: origin/main`

## States

### 1. `refine`

**Job:** Analyze the stakeholder's ask, explore the existing codebase, draft a spec with scope, acceptance criteria, and out-of-scope items.

**Stakeholder interaction:** Uses `needs_feedback` to send the spec to Slack. Loops until the stakeholder approves. Each round revises based on feedback.

**Slack message format:**
> **[Trello Clone] Feature spec: {title}**
>
> I've analyzed your request and drafted a spec. Please review:
>
> **What will be built:** [summary]
> **Acceptance criteria:** [list]
> **Out of scope:** [list]
>
> Does this match what you had in mind? Any changes?

**Result format:**
```yaml
result_format:
  outcome:
    type: enum
    values: [approved, needs_feedback]
    description: "Whether the stakeholder approved the spec"
  spec:
    type: string
    description: "Refined spec with scope, acceptance criteria, out-of-scope"
```

**Transitions:** `approved → preview`

### 2. `preview`

**Job:** Build a UI mockup using the real stack (TanStack Start + shadcn/ui) with hardcoded data. No backend, no API calls, no database. Serve the mockup on a local dev server.

**Stakeholder interaction:** Uses `needs_feedback` to send the preview URL + context to Slack. Loops until the stakeholder approves the design/layout.

**Slack message format:**
> **[Trello Clone] Preview: {title}**
>
> UI mockup is ready for review.
>
> **See it here:** {preview_url}
>
> This is a visual preview only (no backend). Shows how the feature will look with placeholder content and the overall layout.
>
> Does the design/layout work for you?

**Result format:**
```yaml
result_format:
  outcome:
    type: enum
    values: [approved, needs_feedback]
    description: "Whether the stakeholder approved the mockup"
  preview_url:
    type: string
    description: "URL where the mockup is served"
```

**Transitions:** `approved → plan`

### 3. `plan`

**Job:** Read the approved spec and mockup code. Produce a concrete implementation plan and commit it to `docs/plans/{feature-slug}.md`.

**Plan contents:**
- Files to create/modify
- DB schema changes (Alembic migrations)
- API endpoints (FastAPI routes)
- Frontend components and pages
- Unit test plan (pytest, vitest)
- E2E test scenarios (Playwright)
- If first feature: project bootstrapping (FastAPI scaffold, TanStack Start scaffold, docker-compose.yml, Dockerfiles, pre-commit config, Makefile, structured logging setup)

**No stakeholder interaction.** This is a technical artifact.

**Result format:**
```yaml
result_format:
  outcome:
    type: enum
    values: [ready]
    description: "Plan is committed and ready"
  plan:
    type: string
    description: "Relative path to the committed plan doc"
```

**Transitions:** `ready → implement`

### 4. `implement`

**Job:** Follow the plan. Build the full vertical slice: backend + frontend + storage + migrations + unit tests. Apply all code quality tools.

**Code quality inner loop (after every meaningful change):**
- `ruff check .` + `ruff format --check .` (Python lint/format)
- `mypy src/` or equivalent (Python type checking)
- `biome check` (Frontend lint/format)
- `tsc --noEmit` (TypeScript type checking)
- `pre-commit run --all-files` (full hook suite)
- Unit tests: `pytest` (backend), `vitest` (frontend)

Fix all issues before committing.

**Structured logging:** Backend uses `structlog` with JSON output. Frontend uses structured JSON logging.

**First-run bootstrapping:** If the project has no scaffolding, the plan will include it and the implementer executes it as part of the feature delivery.

**Stakeholder interaction:** Uses `needs_feedback` only if genuinely stuck on a product question (not a technical one).

**Result format:**
```yaml
result_format:
  outcome:
    type: enum
    values: [done, blocked, needs_feedback]
    description: "Implementation status"
  summary:
    type: string
    description: "What was implemented and committed"
```

**Transitions:** `done → verify`, `blocked → implement` (retry with failure context)

### 5. `verify`

**Job:** Run the full E2E test suite (Playwright) and analyze structured logs.

**Verification steps:**
1. Start the app stack (backend + frontend + test database)
2. Run Playwright E2E tests
3. Collect and analyze structured logs for errors/warnings
4. If failures: produce a detailed report (which tests failed, relevant log entries, stack traces)

**Result format:**
```yaml
result_format:
  outcome:
    type: enum
    values: [passed, fix_needed]
    description: "Whether E2E tests and log analysis passed"
  report:
    type: string
    description: "Test results summary and any failure details"
```

**Data flow on failure:** The `report` field is written to `issue.fields.verify_report`, which the `implement` worker reads via `{{ issue.fields.verify_report }}` to understand what needs fixing.

**Transitions:** `passed → deploy`, `fix_needed → implement`

### 6. `deploy`

**Job:** Build Docker images for backend and frontend, run `docker compose up` with the full stack (backend + frontend + PostgreSQL), run health checks.

**Health checks:**
- API responds on expected port
- Frontend loads on expected port
- Database is connected (API can read/write)

**Result format:**
```yaml
result_format:
  outcome:
    type: enum
    values: [healthy, fix_needed]
    description: "Whether the Docker stack is up and healthy"
  demo_url:
    type: string
    description: "URL where the deployed app is accessible"
```

**Transitions:** `healthy → demo`, `fix_needed → deploy` (retry with error context)

### 7. `demo`

**Job:** Send the final demo URL and summary to the stakeholder via Slack. Collect their verdict.

**Stakeholder interaction:** Uses `needs_feedback` for the approval loop. If the stakeholder requests changes, transitions back to `implement` for a full fix cycle.

**Slack message format:**
> **[Trello Clone] Ready for review: {title}**
>
> Feature is deployed and fully functional.
>
> **See it here:** {demo_url}
>
> **What's included:** [summary from spec]
> **Acceptance criteria:** ✓ all met
> **E2E tests:** ✓ all passing
>
> Please try it out. Approve to wrap up, or let me know what needs changing.

**Result format:**
```yaml
result_format:
  outcome:
    type: enum
    values: [approved, needs_feedback, changes_requested]
    description: "Stakeholder verdict on the final demo"
  feedback:
    type: string
    description: "What the stakeholder wants changed (if changes_requested)"
    required_when: [changes_requested]
```

**Data flow on changes:** The `feedback` field is written to `issue.fields.change_feedback`, which the `implement` worker reads via `{{ issue.fields.change_feedback }}` to understand what the stakeholder wants changed.

**Transitions:** `approved → done`, `changes_requested → implement`

## Issue Fields

| Field | Type | Description | Set by |
|-------|------|-------------|--------|
| `title` | string | Short feature name | Input |
| `description` | string | Raw stakeholder ask | Input |
| `spec` | string | Refined spec with scope and acceptance criteria | `refine` worker |
| `preview_url` | string | URL where mockup is served | `preview` worker |
| `plan` | string | Path to implementation plan doc | `plan` worker |
| `demo_url` | string | URL where Docker deployment is served | `deploy` worker |
| `verify_report` | string | E2E test/log failure details from verify worker | `verify` worker |
| `change_feedback` | string | Stakeholder's change requests from demo phase | `demo` worker |
| `feedback_context` | string | Stakeholder's latest feedback | orca (auto) |
| `feedback_questions` | string | Questions the worker asked | orca (auto) |
| `failure_context` | string | Error details from last worker failure | orca (auto) |

## Quality Feedback Loops

### Code Quality (inside `implement`)
Linters, type checkers, pre-commit hooks, and unit tests run as the implementer's inner loop. Failures are fixed before committing.

### E2E Verification (`verify` ↔ `implement`)
`implement → verify → [fix_needed] → implement → verify → ...`
Loops until E2E tests pass and logs are clean.

### Docker Deploy (`deploy` retries)
`deploy → [fix_needed] → deploy → ...`
Build/health-check failures trigger retries with error context.

### Stakeholder Approval
- `refine` ↻ loops in-place via `needs_feedback` until spec approved
- `preview` ↻ loops in-place via `needs_feedback` until mockup approved
- `demo` → `changes_requested` → `implement` → `verify` → `deploy` → `demo` (full fix cycle)

## Slack Communication

All stakeholder communication is via Slack only. Every message includes:
1. The URL where the stakeholder can see the preview/demo
2. Short context explaining what is being presented

URLs are `localhost`-based (stakeholder must be on same machine/network). Remote access (ngrok, tunneling) is out of scope for this design.

## File Structure

```
trello-clone-v2/
├── orca.feature.yml
└── prompts/
    ├── refine.md
    ├── preview.md
    ├── plan.md
    ├── implement.md
    ├── verify.md
    ├── deploy.md
    └── demo.md
```

## First-Run Behavior

The trello-clone-v2 repo has no code yet. On first run:
- `plan` detects the empty project and includes full scaffolding in the plan (FastAPI, TanStack Start, Docker, pre-commit, Makefile, structured logging)
- `implement` executes the bootstrapping as part of delivering the first feature
- Subsequent runs skip bootstrapping — the project structure already exists

## Running the Workflow

```bash
# Start the orca daemon (if not running)
orca daemon start --root /Users/agutnikov/work/trello-clone-v2

# Create a task file
cat > task.md << 'EOF'
title: "Empty board view"
description: "I want to see an empty board when I first open the app"
EOF

# Run the workflow
orca task.md -w feature --root /Users/agutnikov/work/trello-clone-v2
```
