# Trello Feature Delivery Workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create an orca workflow (`orca.feature.yml` + 7 prompt templates) that takes a high-level stakeholder request and delivers a tested, Docker-deployed vertical slice with approval gates at refinement, preview, and demo.

**Architecture:** Linear 7-state pipeline: refine → preview → plan → implement → verify → deploy → demo → done. Stakeholder-facing states use `needs_feedback` for Slack communication. Quality loops route verify failures back to implement. Demo changes route through the full implement → verify → deploy → demo cycle.

**Tech Stack:** Orca workflow engine, Jinja2 prompt templates, Claude Code workers

**Target repo:** `/Users/agutnikov/work/trello-clone-v2`

---

### Task 1: Create `orca.feature.yml`

**Files:**
- Create: `/Users/agutnikov/work/trello-clone-v2/orca.feature.yml`

- [ ] **Step 1: Create the workflow config**

```yaml
# Orca workflow: Feature Delivery
#
# Takes a high-level stakeholder request and delivers a fully implemented,
# tested, Docker-deployed vertical slice with approval gates.
#
# Pipeline: refine → preview → plan → implement → verify → deploy → demo → done
#
# Stakeholder communication happens via Slack at three gates:
#   1. refine  — spec approval
#   2. preview — UI mockup approval
#   3. demo    — final deployed feature approval

issue:
  fields:
    title:
      type: string
      description: "Short feature name, e.g. 'Empty board view'"
    description:
      type: string
      description: "Raw stakeholder ask — non-technical, no acceptance criteria"
    spec:
      type: string
      description: "Refined spec with scope, acceptance criteria, and out-of-scope items"
    preview_url:
      type: string
      description: "URL where the UI mockup is served"
    plan:
      type: string
      description: "Relative path to the committed implementation plan doc"
    demo_url:
      type: string
      description: "URL where the Docker-deployed app is accessible"
    verify_report:
      type: string
      description: "E2E test and log analysis failure details from the verify worker"
    change_feedback:
      type: string
      description: "Stakeholder change requests from the demo phase"

initial: refine
max_hops: 25
max_worker_retries: 5
base_branch: origin/main

states:

  # --- Gate 1: Stakeholder spec approval ---
  refine:
    worker:
      kind: claude-code
      prompt: prompts/refine.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [approved, needs_feedback]
          description: "Whether the stakeholder approved the spec"
          values_description:
            approved: "Stakeholder approved — proceed to UI mockup"
            needs_feedback: "Send spec to stakeholder via Slack for review"
        spec:
          type: string
          description: "Refined spec with scope, acceptance criteria, out-of-scope"
        feedback_questions:
          type: string
          description: "Slack message for the stakeholder"
          required_when: [needs_feedback]
    on:
      approved: preview

  # --- Gate 2: Stakeholder mockup approval ---
  preview:
    worker:
      kind: claude-code
      prompt: prompts/preview.md
      timeout: 900
      result_format:
        outcome:
          type: enum
          values: [approved, needs_feedback]
          description: "Whether the stakeholder approved the UI mockup"
          values_description:
            approved: "Design approved — proceed to implementation planning"
            needs_feedback: "Send preview URL to stakeholder via Slack"
        preview_url:
          type: string
          description: "URL where the mockup is served"
        feedback_questions:
          type: string
          description: "Slack message with preview URL and context"
          required_when: [needs_feedback]
    on:
      approved: plan

  # --- Technical planning (no stakeholder interaction) ---
  plan:
    worker:
      kind: claude-code
      prompt: prompts/plan.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [ready]
          description: "Plan is committed and ready"
          values_description:
            ready: "Implementation plan written and committed"
        plan:
          type: string
          description: "Relative path to the committed plan doc"
    on:
      ready: implement

  # --- Full vertical-slice implementation ---
  implement:
    worker:
      kind: claude-code
      prompt: prompts/implement.md
      timeout: 1800
      result_format:
        outcome:
          type: enum
          values: [done, blocked, needs_feedback]
          description: "Implementation status"
          values_description:
            done: "All code written, unit tests pass, hooks pass, committed"
            blocked: "Cannot proceed — technical issue or missing information"
            needs_feedback: "Stuck on a product question — need stakeholder input"
        summary:
          type: string
          description: "What was implemented and committed"
        feedback_questions:
          type: string
          description: "Question for stakeholder"
          required_when: [needs_feedback]
    on:
      done: verify
      blocked: implement

  # --- E2E test and log verification ---
  verify:
    worker:
      kind: claude-code
      prompt: prompts/verify.md
      timeout: 900
      result_format:
        outcome:
          type: enum
          values: [passed, fix_needed]
          description: "Whether all E2E tests pass and logs are clean"
          values_description:
            passed: "All tests pass, no errors in logs"
            fix_needed: "Failures found — details in verify_report"
        report:
          type: string
          description: "Test results summary"
        verify_report:
          type: string
          description: "Detailed failure report for the implement worker"
          required_when: [fix_needed]
    on:
      passed: deploy
      fix_needed: implement

  # --- Docker deployment ---
  deploy:
    worker:
      kind: claude-code
      prompt: prompts/deploy.md
      timeout: 900
      result_format:
        outcome:
          type: enum
          values: [healthy, fix_needed]
          description: "Whether the Docker stack is up and healthy"
          values_description:
            healthy: "All services running, health checks pass"
            fix_needed: "Build or startup failure"
        demo_url:
          type: string
          description: "URL where the app is accessible"
          required_when: [healthy]
    on:
      healthy: demo
      fix_needed: deploy

  # --- Gate 3: Stakeholder demo approval ---
  demo:
    worker:
      kind: claude-code
      prompt: prompts/demo.md
      timeout: 600
      result_format:
        outcome:
          type: enum
          values: [approved, needs_feedback, changes_requested]
          description: "Stakeholder verdict on the deployed feature"
          values_description:
            approved: "Feature accepted — done"
            needs_feedback: "Send demo to stakeholder via Slack"
            changes_requested: "Stakeholder wants changes — route to implement"
        change_feedback:
          type: string
          description: "What the stakeholder wants changed"
          required_when: [changes_requested]
        feedback_questions:
          type: string
          description: "Slack message with demo URL and summary"
          required_when: [needs_feedback]
    on:
      approved: done
      changes_requested: implement
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('/Users/agutnikov/work/trello-clone-v2/orca.feature.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add orca.feature.yml
git commit -m "feat: add orca feature delivery workflow config"
```

---

### Task 2: Create `prompts/refine.md`

**Files:**
- Create: `/Users/agutnikov/work/trello-clone-v2/prompts/refine.md`

- [ ] **Step 1: Create the prompts directory and refine prompt**

```markdown
# Requirement Refinement Agent

You turn vague, non-technical stakeholder requests into actionable feature specs with clear scope and acceptance criteria.

## Issue

**Title:** {{ issue.fields.title }}
**Stakeholder Request:** {{ issue.fields.description }}

{% if issue.fields.feedback_context %}
## Stakeholder Feedback

The stakeholder reviewed your previous spec and responded:

{{ issue.fields.feedback_context }}

Revise the spec based on this feedback. If the stakeholder approved (e.g., "looks good", "approved", "yes"), set outcome to `approved`. If they requested changes, revise and send again with `needs_feedback`.
{% endif %}

## Instructions

### Step 1: Understand the Request

Read the stakeholder's request carefully. This is a non-technical ask from someone who thinks in terms of user experience, not implementation.

### Step 2: Explore the Codebase

Check what already exists in the project:
- Look at the project structure, existing features, and tech stack
- Understand what infrastructure is already in place
- Identify what can be reused vs. what needs to be built

### Step 3: Draft the Spec

Write a spec covering:

1. **Summary** — One paragraph explaining what will be built, written for a non-technical reader
2. **Acceptance Criteria** — Concrete, testable conditions (e.g., "Board page loads at /boards/:id", "Empty state shows a prompt to add lists")
3. **Out of Scope** — What this feature explicitly does NOT include (prevents scope creep)
4. **Technical Notes** — Brief notes on approach (e.g., "New API endpoint", "New DB table") — keep this short

Keep it focused. One feature, one vertical slice. If the request implies multiple features, pick the smallest useful one and put the rest in "Out of Scope."

### Step 4: Send to Stakeholder

{% if not issue.fields.feedback_context %}
This is your first draft. Use `needs_feedback` to send the spec to the stakeholder for review.

Compose a clear Slack message:

```
[Trello Clone] Feature spec: {{ issue.fields.title }}

I've analyzed your request and drafted a spec. Please review:

**What will be built:** [1-2 sentence summary]

**Acceptance criteria:**
- [criterion 1]
- [criterion 2]
- ...

**Out of scope:** [what's NOT included]

Does this match what you had in mind? Reply with "approved" or tell me what to change.
```
{% endif %}

## Output

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add prompts/refine.md
git commit -m "feat: add refine prompt — stakeholder spec approval gate"
```

---

### Task 3: Create `prompts/preview.md`

**Files:**
- Create: `/Users/agutnikov/work/trello-clone-v2/prompts/preview.md`

- [ ] **Step 1: Create the preview prompt**

```markdown
# UI Preview Agent

You build visual UI mockups using the real frontend stack (TanStack Start + shadcn/ui) with hardcoded data. No backend, no API calls, no database — pure frontend showing how the feature will look.

## Issue

**Title:** {{ issue.fields.title }}
**Spec:** {{ issue.fields.spec }}

{% if issue.fields.feedback_context %}
## Stakeholder Feedback

The stakeholder reviewed your mockup and responded:

{{ issue.fields.feedback_context }}

Revise the mockup based on this feedback. If the stakeholder approved (e.g., "looks good", "approved", "yes"), set outcome to `approved`. If they requested changes, update the mockup and send again with `needs_feedback`.
{% endif %}

## Instructions

### Step 1: Read the Spec

Understand what the feature looks like from the user's perspective. Focus on:
- What the user sees on screen
- What interactions are possible
- What data is displayed

### Step 2: Check Project State

Look at the frontend project structure:
- If TanStack Start is not yet set up, scaffold a minimal frontend project first:
  - `pnpm create @tanstack/start`
  - Install shadcn/ui components as needed
- If the frontend already exists, work within the existing structure

### Step 3: Build the Mockup

Create the UI using TanStack Start + shadcn/ui:
- Use **hardcoded data** — no API calls, no fetch, no database
- Build real React components that will be reused in the actual implementation
- Focus on layout, visual design, and static content
- Include placeholder interactions (hover states, visual feedback) but no complex logic
- Use shadcn/ui components for consistency (Button, Card, Input, etc.)

### Step 4: Start the Dev Server

Start the frontend dev server so the stakeholder can view the mockup:

```bash
cd frontend  # or wherever the frontend lives
nohup pnpm dev --port 3001 > /tmp/preview-server.log 2>&1 &
```

Verify it's running: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3001`

### Step 5: Commit the Mockup

```bash
git add -A
git commit -m "preview: {{ issue.fields.title }}"
```

### Step 6: Send to Stakeholder

{% if not issue.fields.feedback_context %}
Use `needs_feedback` to send the preview URL to the stakeholder:

```
[Trello Clone] Preview: {{ issue.fields.title }}

UI mockup is ready for review.

**See it here:** http://localhost:3001

This is a visual preview only (no backend). Shows how the feature will look with placeholder content.

Does the design/layout work for you? Reply with "approved" or tell me what to change.
```
{% endif %}

## Output

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add prompts/preview.md
git commit -m "feat: add preview prompt — stakeholder mockup approval gate"
```

---

### Task 4: Create `prompts/plan.md`

**Files:**
- Create: `/Users/agutnikov/work/trello-clone-v2/prompts/plan.md`

- [ ] **Step 1: Create the plan prompt**

```markdown
# Implementation Planning Agent

You create detailed implementation plans from approved specs and UI mockups. The plan is a technical document that guides the implement worker step by step.

## Issue

**Title:** {{ issue.fields.title }}
**Spec:** {{ issue.fields.spec }}

{% if issue.fields.preview_url %}
**Preview URL:** {{ issue.fields.preview_url }}
{% endif %}

## Instructions

### Step 1: Explore the Current State

Examine the project thoroughly:
- What code exists? What's the project structure?
- Is the project bootstrapped (backend, frontend, docker, pre-commit)?
- What mockup components were built in the preview phase?
- What can be reused from the mockup in the real implementation?

### Step 2: Detect Bootstrap Needs

If the project is missing core scaffolding, include bootstrapping in the plan:

**Backend (if missing):**
- Python 3.12 + uv project with FastAPI
- SQLAlchemy 2.0 with asyncpg for PostgreSQL
- Alembic for migrations
- Pydantic for validation
- structlog for structured JSON logging
- pytest + pytest-asyncio for tests
- Ruff for linting/formatting, mypy (strict) for type checking

**Frontend (if missing):**
- TanStack Start with TypeScript (strict)
- TanStack Query for data fetching
- TanStack Router (file-based routing)
- shadcn/ui for components
- Vitest + Testing Library for tests
- Biome for linting/formatting

**Infrastructure (if missing):**
- `docker-compose.yml` — PostgreSQL 16, backend, frontend (all containerized)
- `Dockerfile` for backend (Python/FastAPI)
- `Dockerfile` for frontend (Node/TanStack Start)
- `.pre-commit-config.yaml` — ruff, mypy, biome, tsc, trailing-whitespace
- `Makefile` — convenience commands (up, down, dev, lint, test, e2e)

### Step 3: Write the Implementation Plan

Create `docs/plans/{{ issue.fields.title | lower | replace(' ', '-') }}.md` with:

1. **Overview** — What this plan delivers (one paragraph)
2. **Prerequisites** — What must exist before implementation (bootstrap items if needed)
3. **Database Schema** — Tables, columns, types, migrations
4. **API Endpoints** — Routes, request/response shapes, status codes
5. **Frontend Components** — Pages, components, which mockup code to reuse
6. **Unit Test Plan** — What to test, with example test signatures
7. **E2E Test Plan** — User flows to test with Playwright, with scenario descriptions
8. **File List** — Every file to create or modify, with one-line description

Keep it concrete. File paths, function names, data shapes. No vague "implement the feature" steps.

### Step 4: Commit the Plan

```bash
git add docs/plans/
git commit -m "plan: {{ issue.fields.title }}"
```

## Output

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add prompts/plan.md
git commit -m "feat: add plan prompt — implementation planning"
```

---

### Task 5: Create `prompts/implement.md`

**Files:**
- Create: `/Users/agutnikov/work/trello-clone-v2/prompts/implement.md`

- [ ] **Step 1: Create the implement prompt**

```markdown
# Implementation Agent

You build the full vertical slice — backend, frontend, storage, migrations, and unit tests — following the implementation plan. You enforce code quality at every step.

## Issue

**Title:** {{ issue.fields.title }}
**Spec:** {{ issue.fields.spec }}
**Plan:** {{ issue.fields.plan }}

{% if issue.fields.verify_report %}
## Verification Failures

The verify agent found issues with your previous implementation:

{{ issue.fields.verify_report }}

Fix these issues. Focus on what the report describes — do not rewrite unrelated code.
{% endif %}

{% if issue.fields.change_feedback %}
## Stakeholder Change Request

The stakeholder reviewed the deployed demo and requested changes:

{{ issue.fields.change_feedback }}

Implement these changes. Keep the scope minimal — only change what the stakeholder asked for.
{% endif %}

{% if issue.fields.failure_context %}
## Previous Failure

Your previous attempt failed:

{{ issue.fields.failure_context }}

Address this issue before proceeding.
{% endif %}

{% if issue.fields.feedback_context %}
## Stakeholder Clarification

You asked the stakeholder a question and they responded:

{{ issue.fields.feedback_context }}

Use this information to continue your implementation.
{% endif %}

## Instructions

### Step 1: Read the Plan

Read the implementation plan at `{{ issue.fields.plan }}`. This is your roadmap — follow it.

If returning from a verify failure or stakeholder change request, focus on the specific issues described above rather than re-implementing everything.

### Step 2: Implement

Follow the plan step by step:
- Backend: FastAPI routes, SQLAlchemy models, Alembic migrations, Pydantic schemas
- Frontend: TanStack Start pages, React components, TanStack Query hooks
- Reuse mockup components from the preview phase where possible
- Use structlog (backend) and structured JSON logging (frontend)

### Step 3: Write Unit Tests

- Backend: pytest + pytest-asyncio — test each endpoint and business logic function
- Frontend: Vitest + Testing Library — test components and hooks
- Run tests and ensure they all pass before proceeding

### Step 4: Code Quality Checks

Run ALL of these after every meaningful change. Fix any issues before committing.

**Backend:**
```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src/ --strict
uv run pytest
```

**Frontend:**
```bash
pnpm biome check .
pnpm tsc --noEmit
pnpm vitest run
```

**Full suite:**
```bash
pre-commit run --all-files
```

Do NOT skip any of these. Do NOT commit code that fails any check.

### Step 5: Commit

Stage and commit all changes:

```bash
git add -A
git commit -m "feat: {{ issue.fields.title }}"
```

If pre-commit hooks fail, fix the issues and retry the commit.

## Constraints

- Follow the plan. Do not add features not in the plan.
- Do not skip linters, type checkers, or tests.
- If you cannot proceed due to a technical issue, use outcome `blocked`.
- If you need a product decision from the stakeholder, use outcome `needs_feedback`.
- Do not modify shared infrastructure files unless the plan explicitly says to.

## Output

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add prompts/implement.md
git commit -m "feat: add implement prompt — vertical slice builder"
```

---

### Task 6: Create `prompts/verify.md`

**Files:**
- Create: `/Users/agutnikov/work/trello-clone-v2/prompts/verify.md`

- [ ] **Step 1: Create the verify prompt**

```markdown
# Verification Agent

You run the full E2E test suite and analyze structured logs to verify the implementation works end-to-end before it goes to Docker deployment.

## Issue

**Title:** {{ issue.fields.title }}
**Spec:** {{ issue.fields.spec }}

{% if issue.fields.failure_context %}
## Previous Failure

Your previous verification attempt failed:

{{ issue.fields.failure_context }}

Check if the issue was resolved before re-running tests.
{% endif %}

## Instructions

### Step 1: Start the Application Stack

Start the backend and frontend with a test database:

```bash
# Start test database (if docker-compose exists)
docker compose up -d postgres-test 2>/dev/null || true

# Start backend
cd backend
uv run uvicorn app.main:app --port 8000 &
BACKEND_PID=$!

# Start frontend
cd ../frontend
pnpm dev --port 3000 &
FRONTEND_PID=$!

# Wait for services to be ready
sleep 5
```

If the project uses a different structure, adapt accordingly. Check existing Makefile or package.json scripts.

### Step 2: Run E2E Tests

```bash
cd e2e
pnpm playwright test --reporter=list
```

Capture the full output including any failures, stack traces, and screenshots.

### Step 3: Analyze Structured Logs

Check backend logs for errors and warnings:

```bash
# Check for errors in structured logs
cat /tmp/backend.log | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        entry = json.loads(line)
        if entry.get('level') in ('error', 'critical', 'warning'):
            print(json.dumps(entry, indent=2))
    except: pass
"
```

Check frontend console output for errors if available.

### Step 4: Clean Up

```bash
kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
docker compose stop postgres-test 2>/dev/null || true
```

### Step 5: Compile Report

If all tests pass and logs are clean:
- Set outcome to `passed`
- Write a brief summary in `report`

If any tests fail or logs show errors:
- Set outcome to `fix_needed`
- Write a detailed `verify_report` including:
  - Which tests failed and why (include assertion errors)
  - Relevant log entries (include timestamps and context)
  - Stack traces if available
  - Screenshot paths if Playwright captured them
  - Your assessment of what needs fixing

Be specific. "Test failed" is useless. "test_create_board failed: POST /boards returned 500, backend log shows 'relation boards does not exist' — migration not applied" is actionable.

## Output

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add prompts/verify.md
git commit -m "feat: add verify prompt — E2E test and log verification"
```

---

### Task 7: Create `prompts/deploy.md`

**Files:**
- Create: `/Users/agutnikov/work/trello-clone-v2/prompts/deploy.md`

- [ ] **Step 1: Create the deploy prompt**

```markdown
# Deployment Agent

You build Docker images and deploy the full application stack (backend + frontend + PostgreSQL) using Docker Compose, then verify everything is healthy.

## Issue

**Title:** {{ issue.fields.title }}

{% if issue.fields.failure_context %}
## Previous Failure

Your previous deployment attempt failed:

{{ issue.fields.failure_context }}

Diagnose and fix the issue before retrying.
{% endif %}

## Instructions

### Step 1: Check Docker Setup

Verify that Docker files exist:
- `docker-compose.yml` (or `compose.yml`)
- `backend/Dockerfile` (or equivalent)
- `frontend/Dockerfile` (or equivalent)

If any are missing, this is a bug — the plan and implement phases should have created them. Report `fix_needed` with details.

### Step 2: Stop Existing Containers

```bash
docker compose down --remove-orphans 2>/dev/null || true
```

### Step 3: Build and Start

```bash
docker compose up -d --build
```

If the build fails, capture the full error output and report `fix_needed`.

### Step 4: Wait for Services

Wait for all services to be ready (up to 60 seconds):

```bash
for i in $(seq 1 12); do
  # Check backend
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "Backend is ready"
    break
  fi
  echo "Waiting for backend... ($i/12)"
  sleep 5
done
```

Repeat for frontend (e.g., `http://localhost:3000`).

### Step 5: Health Checks

Run these health checks and capture results:

1. **Backend API:** `curl -sf http://localhost:8000/health`
   - Expected: 200 OK with health status
2. **Frontend:** `curl -sf http://localhost:3000`
   - Expected: 200 OK with HTML content
3. **Database connectivity:** `curl -sf http://localhost:8000/health` should confirm DB connection
   - Or: `docker compose exec postgres pg_isready`

### Step 6: Report Result

If all health checks pass:
- Set outcome to `healthy`
- Set `demo_url` to `http://localhost:3000`

If any check fails:
- Set outcome to `fix_needed`
- Include the full error output: which service failed, docker logs, curl output
- Run `docker compose logs` and include relevant lines

## Output

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add prompts/deploy.md
git commit -m "feat: add deploy prompt — Docker deployment and health checks"
```

---

### Task 8: Create `prompts/demo.md`

**Files:**
- Create: `/Users/agutnikov/work/trello-clone-v2/prompts/demo.md`

- [ ] **Step 1: Create the demo prompt**

```markdown
# Demo Agent

You present the fully deployed feature to the stakeholder via Slack and collect their verdict. You compose clear, non-technical messages with a URL and context.

## Issue

**Title:** {{ issue.fields.title }}
**Spec:** {{ issue.fields.spec }}
**Demo URL:** {{ issue.fields.demo_url }}

{% if issue.fields.feedback_context %}
## Stakeholder Response

The stakeholder reviewed the demo and responded:

{{ issue.fields.feedback_context }}

Interpret their response:
- If they approved (e.g., "looks good", "approved", "ship it", "yes") → set outcome to `approved`
- If they want changes (e.g., "change X", "the button should be...", "I don't like...") → set outcome to `changes_requested` and write their feedback to `change_feedback`
- If you need to clarify something → set outcome to `needs_feedback` with a follow-up question
{% endif %}

## Instructions

### Step 1: Verify the Demo is Running

Check that the deployed app is accessible:

```bash
curl -sf {{ issue.fields.demo_url }} > /dev/null 2>&1
```

If not running, check Docker status:
```bash
docker compose ps
docker compose logs --tail=20
```

If the stack is down, restart it: `docker compose up -d`

### Step 2: Prepare the Demo Summary

Read the spec and extract:
- What was built (in user-facing terms)
- Acceptance criteria that were met
- How to interact with the feature (click paths, URLs)

### Step 3: Send to Stakeholder

{% if not issue.fields.feedback_context %}
Use `needs_feedback` to send the demo to the stakeholder:

```
[Trello Clone] Ready for review: {{ issue.fields.title }}

Feature is deployed and fully functional.

**See it here:** {{ issue.fields.demo_url }}

**What's included:**
[bullet list from spec — user-facing language, not technical]

**How to try it:**
[brief click-path, e.g., "Open the URL, you'll see an empty board with a prompt to add your first list"]

**All acceptance criteria met. E2E tests passing.**

Please try it out. Reply "approved" to wrap up, or tell me what needs changing.
```
{% endif %}

## Output

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add prompts/demo.md
git commit -m "feat: add demo prompt — stakeholder demo approval gate"
```

---

### Task 9: Validate the Complete Workflow

**Files:**
- Read: `/Users/agutnikov/work/trello-clone-v2/orca.feature.yml`
- Read: All files in `/Users/agutnikov/work/trello-clone-v2/prompts/`

- [ ] **Step 1: Validate config structure**

Run from the orca project directory:

```bash
cd /Users/agutnikov/work/orca
uv run python -c "
from orca.engine.config import load_config
config = load_config('/Users/agutnikov/work/trello-clone-v2/orca.feature.yml')
print(f'Workflow loaded: {len(config.types)} type(s)')
for type_name, type_def in config.types.items():
    print(f'  {type_name}: {len(type_def.states)} states')
    for state_name in type_def.states:
        print(f'    - {state_name}')
print('Validation passed!')
"
```

Expected: Validation passes, lists 7 states (refine, preview, plan, implement, verify, deploy, demo)

- [ ] **Step 2: Verify all prompts are referenced**

Check that every state's prompt file exists:

```bash
cd /Users/agutnikov/work/trello-clone-v2
for f in prompts/refine.md prompts/preview.md prompts/plan.md prompts/implement.md prompts/verify.md prompts/deploy.md prompts/demo.md; do
  if [ -f "$f" ]; then
    echo "OK: $f"
  else
    echo "MISSING: $f"
  fi
done
```

Expected: All 7 files show "OK"

- [ ] **Step 3: Verify Jinja2 templates render**

```bash
cd /Users/agutnikov/work/orca
uv run python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/Users/agutnikov/work/trello-clone-v2'))
for name in ['prompts/refine.md', 'prompts/preview.md', 'prompts/plan.md', 'prompts/implement.md', 'prompts/verify.md', 'prompts/deploy.md', 'prompts/demo.md']:
    t = env.get_template(name)
    print(f'OK: {name} ({len(t.module.__dict__)} blocks)')
print('All templates parse!')
"
```

Expected: All 7 templates parse without errors

- [ ] **Step 4: Create example task file**

Create an example task file for testing:

```bash
cat > /Users/agutnikov/work/trello-clone-v2/tasks/empty-board.md << 'EOF'
title: "Empty board view"
description: "I want to see an empty board when I first open the app"
EOF
```

- [ ] **Step 5: Final commit**

```bash
cd /Users/agutnikov/work/trello-clone-v2
git add tasks/
git commit -m "feat: add example task file for workflow testing"
```
