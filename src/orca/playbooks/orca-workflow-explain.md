# Playbook: Explain a Workflow

Generate a plain-language, language-localized explanation of an orca workflow
for the web UI. The target may be a production workflow
(`.orca/{flow}.yml`) or an eval workflow
(`.orca/evals/{flow}/eval-flow.yml`). The output is a single JSON file under
`.orca-state/explanations/{flow}.{lang}.json` that the daemon serves at
`GET /api/explanations/{flow}` and the web app renders at
`http://localhost:{browser_port}/explain/{flow}?lang={lang}` (Mermaid state diagram +
per-state cards + optional scenario walkthrough). The `browser_port` is the
TCP port the daemon bound for the browser app — usually `7891`, but the
daemon falls back to a free port if `7891` is busy (e.g. another orca daemon
is running for a different repo). Read it from `orca_daemon_status`
(`browser_port` field) or `orca daemon status`.

Audience for the rendered page: **a developer who just kicked off an eval and
wants to understand the slice they're testing**, in the language they asked
for. Plain language, but assume they read code. Translate the *intent* of each
prompt — do not paste prompt text verbatim. Inline any rule the prompt
references (e.g. `§5.2`, "see playbook X") — the reader cannot follow links
from inside the rendered card.

## The single most important framing rule

**An eval flow IS the production slice it tests.** The eval wraps the body
state(s) with a structural grader (`assert`) that reads `assertions.md` and
emits `passed`/`failed`/`inconclusive`. That grader is *scaffolding* — the
person who just hit "run eval" wants to understand the body, not the wrapper.

When the resolved flow is an eval workflow (`.orca/evals/<name>/eval-flow.yml`):

- **Hide the grader entirely.** Detect it: a state whose only purpose is to
  grade — typically named `assert`/`grade`/`check`, with `result_format.outcome`
  exactly `[passed, failed, inconclusive]` (in any order), and whose prompt
  references `assertions.md`. Do not emit it in `states[]`. Do not draw it in
  `diagram_mermaid`. Do not list it in transitions.
- **Body outcomes terminate.** Every body-state transition that targeted the
  grader now targets `[*]` in the diagram. The `transitions[].to` field for the
  body state should be `"[done]"` (a virtual sink the renderer treats as
  terminal). The transition's `explain` text describes *what the outcome
  means*, not "we route to assert"-style plumbing.
- **`title` and `summary` describe the body**, not the eval. Open with what
  the production state *does* for the workflow it lives in. Do not say "smoke
  eval", "structural check", "grading", or anything wrapper-flavoured.
- **Emit a top-level `input` block** describing what the worker actually sees
  on boot (see Step 2.5). This replaces the older `walkthrough` for eval
  flows.

For production flows (`.orca/{flow}.yml`), none of this applies — render the
full graph as before, and use `walkthrough` if a separate `eval` is supplied.

## Required reading (you, the agent — not the user)

- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — workflow YAML structure, `result_format`, template variables.

## When to use this

- The user asks "explain this flow", "show me how X works", "walk me through the run-evals flow", "объясни этот поток на русском", etc.
- The user invokes the playbook by name with a flow argument.

## Inputs

- **`flow`** (required) — either the YAML stem under `.orca/`, e.g. `develop`,
  or an eval directory name under `.orca/evals/`, e.g. `review-catches-sql-injection`.
- **`lang`** (optional, default `en`) — ISO 639-1 code, e.g. `en`, `ru`, `es`, `de`, `fr`.
- **`eval`** (optional) — subdirectory name under `.orca/evals/`. When provided while explaining a production workflow, a "walkthrough" section is added that anchors the explanation in this concrete scenario. When `flow` itself resolves to an eval workflow, use that eval's own `input.md`/`assertions.md` as walkthrough context.

If `flow` is missing, stop and ask. Don't guess from `.orca/` directory listing.

## Output

A single JSON file at `.orca-state/explanations/{flow}.{lang}.json` matching the schema in [Step 7](#step-7--write-the-json). Then print the URL for the user; open it in the browser only when the current host/tooling allows that.

---

## Step 1 — Confirm inputs and prerequisites

- Resolve the workflow config:
  - If `.orca/{flow}.yml` exists, explain that production workflow.
  - Else if `.orca/evals/{flow}/eval-flow.yml` exists, explain that eval workflow.
  - Else stop with a clear message ("no workflow or eval named X found under .orca/").
- If `eval` is provided separately, `.orca/evals/{eval}/` must exist. If not, stop similarly.
- The orca daemon is running. Check via the `orca_daemon_status` MCP tool when available; otherwise run `orca daemon status`. If down, tell the user to start it (`orca daemon start`) and stop.

## Step 2 — Read the artefacts

Read these files (use the file-reading tools available to you, not `cat`):

- The resolved workflow config (`.orca/{flow}.yml` or `.orca/evals/{flow}/eval-flow.yml`).
- For every `state.worker.prompt: path/to.md` entry, read that prompt file. The path is relative to the directory containing the resolved config (`.orca/` for production flows, `.orca/evals/{flow}/` for eval flows).
- For states with inline `prompt: { text: "..." }`, capture the inline string.
- If explaining an eval workflow, read `.orca/evals/{flow}/input.md` and `.orca/evals/{flow}/assertions.md`.
- If `eval` provided separately: read `.orca/evals/{eval}/input.md`, `.orca/evals/{eval}/assertions.md`, and any other small files needed for context.

If a referenced prompt file is missing, flag it but continue — emit a state with `what_the_prompt_asks` set to "(prompt file missing — could not summarise)" in the target language.

## Step 2.5 — Eval workflows: read the state branch

**Skip this step for production flows.** For eval flows only:

The eval's run worktree is checked out from the git ref `state_ref` declared
in `input.md`'s frontmatter (typically `orca-eval-state/<eval-name>`). That
ref's tree IS the input the worker sees on boot — its files, its absence of
files, its dirty edges. Read it with **`git`, not the working tree**:

```bash
git ls-tree -r --name-only <state_ref>           # full file list
git ls-tree -r --name-only <state_ref> | wc -l   # how empty is it?
git diff --stat main..<state_ref>                # what's different from main
git log -1 --pretty=format:'%h %s' <state_ref>   # tip commit
```

Capture also:

- The `input.md` frontmatter values (`title`, `description`, `branch`,
  `base_url`, `sandbox`, anything else under YAML frontmatter). Those are
  the `issue.fields.*` the body state will template into its prompt — they
  literally substitute into the rendered worker prompt.
- The body state's `inputs` list (the `{{ issue.fields.X }}` references you
  found in Step 2). Cross-reference: the frontmatter values flow into those
  fields. If a field is `TODO` or empty in the frontmatter, say so — the
  worker will see the literal placeholder.

Use this to compose the `input` block (Step 4) and to *predict the outcome*
honestly in `examples` (Step 4). An empty state-branch tree is the most
important signal — many smoke evals ship with the tree empty before the
author seeds a real scenario, and the body will hit its earliest sanity
check (e.g. "not at repo root", "no plan file") and exit early. **Say that.**

## Step 3 — Derive the structural fields

From the YAML, derive for each state (skipping the grader entirely for eval flows):

- `name` — the state's YAML key (e.g. `select-eval`).
- `worker_kind` — the value of `state.worker.kind` if present (e.g. `claude-code`). Omit field if no `worker` block.
- `is_passive: true` when there is no `worker` block.
- `inputs` — best-effort scan of the prompt template for `{{ issue.fields.X }}` references plus any inputs explicitly described in the prompt's prose. List the field names as `["title", "description", ...]`. **This is best-effort by string scan — note this fact internally; do not promise exhaustiveness.**
- `outputs` — keys from `state.worker.result_format` (if present). For each, the key name only (e.g. `["outcome", "selected"]`).
- `transitions` — from each `state.on` rule. For simple transitions, `to` is the target string. For decompose rules, `to` is `then` when present, otherwise `"[children]"` because the parent waits for children before continuing. Each transition is `{on: event, to: target_state, explain: <see Step 4>}`.

**Eval-flow rewrite:** for every transition whose target is the grader
state, replace `to` with `"[done]"`. The renderer treats `[done]` as a virtual
terminal, so the user sees the outcome as the body's *exit*, not as a step
toward more processing.

## Step 4 — Write the plain-language fields, in the target language

For each state, write in `{lang}`:

- `one_line` — one short sentence: what does this state *do*? (Not how.)
- `what_the_prompt_asks` — **a self-contained, first-principles teaching
  explanation, rendered as markdown.** See "How to write
  `what_the_prompt_asks`" below.
- `transitions[].explain` — one sentence: what does this outcome *mean*?
  For eval flows, this is the user-visible verdict ("the branch is on main or
  has no plan — nothing to test"), not routing plumbing ("we go to assert").

For the top level:

- `title` — short page title in `{lang}` (e.g. "Preflight: pick the next
  state", "Preflight: выбираем следующее состояние"). For eval flows, name
  the **body state**, not the eval.
- `summary` — 1-2 sentences total, in `{lang}`. Describe what the body does
  for its production workflow. For eval flows, do not mention "smoke",
  "structural eval", or the grader — the user already knows they ran an eval.

Names of states, transition `on`/`to` values, and `result_format` field names
are **identifiers** — do not translate them. The diagram and structural fields
keep their original identifiers; only prose is localized.

### How to write `what_the_prompt_asks`

This is the centrepiece of the page. The reader is a dev who just kicked off
a run and wants to *understand the slice*, not skim a summary. **It is OK to
make this long — but keep it cleanly structured.** Render as markdown.

Use this skeleton (adapt headings to the state — these are the common
sections, not a rigid template):

```markdown
**Mission.** One paragraph: what is this state's job in the workflow, framed
from the perspective of someone running it. What problem does it solve?

## Steps the worker takes

1. **Step name.** What it does in one sentence. If the prompt runs a specific
   shell command or check, paste a *minimal* version of it (do not copy the
   whole script; keep enough that the reader sees the intent):
   ```bash
   curl -sS --max-time 8 "$BASE_URL"   # non-2xx → outcome `waiting`
   ```
2. **Next step.** And so on.

## Rules the worker applies

Inline any rule the prompt references by section number (e.g. `§5.2`,
"see playbook X §4"). Do not link out — paste the rule itself. Tables work
well for classification rules:

| Class | Signal | Outcome it pushes toward |
|---|---|---|
| `implemented` | real test body | finalize-only |
| `empty-body` | `async () => {}` | needs implementing |

## How outcomes are decided

Plain-language decision rules, in the same order the prompt evaluates them.
Use code blocks for pseudo-logic when it's clearer than prose:

```
if any test is "fixme-broken"  → waiting (escalation)
elif any test is throwing/empty → recon_required OR recon_exists_ready
elif every test is implemented  → ready_finalize_only
```

## Examples — what input produces what outcome

Concrete scenarios. Pick 3–5 that span the outcome space. Each one
two-or-three sentences max:

- **Branch with two implemented tests, AGENTS.md last updated last week,
  diff touches only `tests/e2e/payments/`.** → `ready_finalize_only`. Every
  picked test has a real body, and recon for `payments` is fresh.
- **Branch with one `empty-body` test, no `AGENTS.md` for that area.**
  → `recon_required`. There's work to do and the area's discovery doc
  doesn't exist yet.
- **Branch is `main`.** → `nothing_to_do`. The Step-2 guard exits before
  classification even starts.
```

Discipline:

- **Inline rules, do not link.** If the prompt says "classify per §5.2",
  open §5.2 and write the actual rule on the page. The reader cannot follow
  the link.
- **Show, don't just say.** A 2-line shell snippet beats a paragraph of
  prose describing the same command. A table beats a paragraph listing
  six classes. Examples beat decision-tree narration.
- **Skip plumbing the user does not need.** Don't explain how the result
  file is written, where Jinja templating substitutes `{{ result_path }}`,
  or which YAML key holds the prompt path. The reader wants to understand
  the *idea*.
- **Plain language for devs.** Devs can read code blocks and shell. They
  cannot read jargon-soup ("the per-test classification is consumed by the
  outcome resolver downstream"). State plainly: "for each test in the plan,
  decide which of six classes it is".
- **No verbatim prompt text** for prompts longer than a paragraph. Quote
  short pieces (a command, a regex) only when the literal token matters.
- **Mention `failure_context` / retry seams** only if the worker actually
  uses them; otherwise skip.

### Eval flows: rewrite outcome `explain` text

For each body-state transition whose target became `[done]` (Step 3), the
`explain` text is what the user sees in the outcome list. Write it as the
verdict, not the routing:

| ✗ Wrong (routing) | ✓ Right (verdict) |
|---|---|
| "Worker decided recon is needed — in prod we go to recon, here we cut to assert." | "Recon is missing or stale for an affected area — the workflow would refresh discovery next." |
| "Empty plan or branch=main — nothing to do." | "Branch is `main` or `tests/test-plans/<branch>.json` is empty — there is nothing to test." |

## Step 4.5 — Eval flows: compose the `input` block

**Skip for production flows.**

The `input` block is a top-level object describing what the worker sees on
boot. Author it from Step 2.5's data:

```json
"input": {
  "title": "<localized section heading, e.g. 'Что лежит на state-ветке'>",
  "description": "<markdown: one short paragraph + optional file listing + a note about what the worker will actually do with this tree>",
  "fields": { "branch": "...", "base_url": "...", "sandbox": "..." },
  "fields_label": "<localized header for the fields table, e.g. 'Подставляется в промпт'>"
}
```

Rules:

- **`description` must be specific.** Do not write "a prepared scenario lives
  on the state branch". Say what's there: number of files, paths that
  matter, whether the tree is empty. Use a code block if a tree listing
  helps:
  ```text
  $ git ls-tree -r --name-only <state_ref>
  (no files)
  ```
- **State the consequence.** If the tree is empty, the worker will hit its
  first sanity check and exit early — say which check and which outcome.
  This is the most useful thing you can tell the reader.
- **`fields` is the frontmatter values verbatim** (or a redacted form). Show
  literal `TODO` placeholders if that's what input.md ships with — the user
  needs to know the scenario isn't seeded yet.
- **Localize `title` and `fields_label`**, keep `fields` keys as identifiers.

## Step 5 — Generate the Mermaid diagram

Build a `stateDiagram-v2` snippet as a single multi-line string:

    stateDiagram-v2
        [*] --> {initial_state}
        {state_a} --> {state_b} : {on_value}
        ...
        {terminal_state} --> [*]

Rules:

- Use the value of `initial:` in the YAML as the entry. If absent, use the
  first state defined.
- For each `state.on.{event}: {target}`, emit one line.
- There is no `terminal:` block in the current schema. The built-in terminal
  sink is `done`. For each transition that targets `done`, emit
  `{state} --> [*] : {on_value}`. Passive states with no `worker` and no
  `on:` are manual wait states, not terminal states; render them with no
  outgoing edge unless a manual transition is described elsewhere.
- The built-in `failed` target is a control directive, not a resting state.
  Render it as `{state} --> failed : {on_value}` only if doing so helps explain
  retry/failure handling; do not add `failed --> [*]`.
- Mermaid identifiers don't allow hyphens — replace `-` with `_` in state
  names *for the diagram only*. Keep the original names in `states[].name`.
- **Eval flows:** the grader is hidden, so every transition that targeted
  the grader becomes `{body_state} --> [*] : {on_value}` in the diagram.
  Do not emit any line referencing the grader. The diagram shows the body
  fanning out into outcomes that terminate the run — that is the slice the
  reader cares about.

## Step 6 — Walkthrough (production flows only)

**Skip entirely for eval flows** — the `input` block (Step 4.5) and the
"Examples" section embedded in `what_the_prompt_asks` (Step 4) already cover
the scenario; a separate walkthrough is redundant. Omit the `walkthrough` key
from the JSON for eval flows.

For production flows when an `eval` is supplied as a separate argument, write
one entry per state:

- `state` — state name (original identifier, not translated).
- `what_happens` — one or two sentences in `{lang}` describing what would
  occur at this state given the eval's scenario.
- `expected_outcome` — short prediction of the outcome enum value or the
  shape of the result, in `{lang}`.

Use the eval's `input.md`, `assertions.md`, and state-branch notes as context.
If you cannot reasonably predict (e.g. the eval is about prompt quality, not
flow behaviour), say so in `what_happens` — don't fabricate.

## Step 7 — Write the JSON

Create the directory if it doesn't exist:

    mkdir -p .orca-state/explanations

Write the file at `.orca-state/explanations/{flow}.{lang}.json`. The exact
shape:

    {
      "flow": "{flow}",
      "language": "{lang}",
      "title": "...",
      "summary": "...",
      "diagram_mermaid": "stateDiagram-v2\n    [*] --> ...",
      "input": {
        "title": "...",
        "description": "markdown with backticks and code blocks",
        "fields": { "branch": "...", "base_url": "..." },
        "fields_label": "..."
      },
      "states": [
        {
          "name": "select-eval",
          "one_line": "...",
          "what_the_prompt_asks": "markdown body — see Step 4",
          "inputs": ["title", "description"],
          "outputs": ["outcome", "selected"],
          "transitions": [
            { "on": "done", "to": "[done]", "explain": "..." }
          ],
          "worker_kind": "claude-code",
          "is_passive": false
        }
      ],
      "walkthrough": [
        { "state": "select-eval", "what_happens": "...", "expected_outcome": "..." }
      ],
      "generated_at": "{ISO 8601 timestamp, e.g. 2026-05-21T11:00:00.000Z}"
    }

Omit:

- `input` for production flows (it's an eval-flow concept).
- `walkthrough` for eval flows AND for production flows when no `eval`
  was supplied. When omitted, the key must be absent — not present-but-empty.
- `worker_kind` and `is_passive` per-state when they don't apply.

## Step 8 — Print the URL

Read the daemon's browser port (`browser_port` from `orca_daemon_status` /
`orca daemon status`) — do **not** assume `7891`, since the daemon may have
fallen back to a different free port. Then print the URL clearly to the user:

    http://localhost:{browser_port}/explain/{flow}?lang={lang}

If the host environment allows browser-opening commands and the user has not restricted tool use, you may also open it:

- macOS: `open http://localhost:{browser_port}/explain/{flow}?lang={lang}`
- Linux: `xdg-open http://localhost:{browser_port}/explain/{flow}?lang={lang}`
- Windows: `start http://localhost:{browser_port}/explain/{flow}?lang={lang}`

## Pitfall checks

- **Do not paste prompt text verbatim** into `what_the_prompt_asks` when the
  prompt is more than a paragraph. The goal is plain language with inlined
  rules.
- **Inline the rules, do not link.** A prompt that says "classify per §5.2"
  is delegating to a section the reader can't see. Open §5.2 and write the
  actual rule (or its essence) into the explanation. Same for `playbook X`,
  `recon.md`, etc.
- **Identifiers stay in English**: state names, `on:` values, `result_format`
  field names, `worker.kind` values.
- **Mermaid state IDs can't have hyphens**: replace `-` with `_` in the
  diagram only.
- **Best-effort inputs scan**: a `{{ issue.fields.X }}` in a Jinja `{% if %}`
  branch still counts as an input. List it. Don't try to be exhaustive — a
  prompt that conditionally reads `notes` is OK to list `notes` once.
- **Eval flows hide the grader.** If you find yourself writing `assert` as a
  state name, a transition target, or a `to:` value, go back to Step 3.
  The grader is invisible to the reader.
- **Eval flows describe the body.** If `title`/`summary` mentions "smoke",
  "grading", "structural eval", or any wrapper concept — rewrite. The reader
  knows they're running an eval; they want to understand the body.
- **No `walkthrough` for eval flows.** Use the `input` block + embedded
  examples instead.
- **No `walkthrough` without `eval`** (production flows): if no eval was
  provided, the `walkthrough` key must be absent from the output, not
  present-but-empty.
- **`input.description` is markdown**: code blocks, lists, and `**bold**`
  render. Use them. A literal command and its output beat three sentences of
  prose.
- **Daemon must be up before opening the URL** — if it isn't, the user gets a
  connection-refused error in the browser. Check with `orca_daemon_status` or
  `orca daemon status` in Step 1.
