# Playbook: Explain a Workflow

Generate a plain-language, language-localized explanation of an orca workflow
for the web UI. The target may be a production workflow
(`.orca/{flow}.yml`) or an eval workflow
(`.orca/evals/{flow}/eval-flow.yml`). The output is a single JSON file under
`.orca-state/explanations/{flow}.{lang}.json` that the daemon serves at
`GET /api/explanations/{flow}` and the web app renders at
`http://localhost:7891/explain/{flow}?lang={lang}` (Mermaid state diagram +
per-state cards + optional scenario walkthrough).

Audience for the rendered page: a smart non-engineer. Avoid jargon. Translate
the *intent* of each prompt — do not paste prompt text verbatim.

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

## Step 3 — Derive the structural fields

From the YAML, derive for each state:

- `name` — the state's YAML key (e.g. `select-eval`).
- `worker_kind` — the value of `state.worker.kind` if present (e.g. `claude-code`). Omit field if no `worker` block.
- `is_passive: true` when there is no `worker` block.
- `inputs` — best-effort scan of the prompt template for `{{ issue.fields.X }}` references plus any inputs explicitly described in the prompt's prose. List the field names as `["title", "description", ...]`. **This is best-effort by string scan — note this fact internally; do not promise exhaustiveness.**
- `outputs` — keys from `state.worker.result_format` (if present). For each, the key name only (e.g. `["outcome", "selected"]`).
- `transitions` — from each `state.on` rule. For simple transitions, `to` is the target string. For decompose rules, `to` is `then` when present, otherwise `"[children]"` because the parent waits for children before continuing. Each transition is `{on: event, to: target_state, explain: <see Step 4>}`.

## Step 4 — Write the plain-language fields, in the target language

For each state, write in `{lang}`:

- `one_line` — one short sentence: what does this state *do*? (Not how.)
- `what_the_prompt_asks` — 2-4 sentences. Translate the intent of the prompt:
  what does the worker need to accomplish here, in what order, with what
  constraints. **Do not** include prompt text verbatim for prompts longer than
  a paragraph. **Do** convey the worker's task in plain language.
- `transitions[].explain` — one sentence: when does this transition fire?
  E.g. "When the user submits the form" or "When the worker exits cleanly."

For the top level:

- `title` — short page title in `{lang}` (e.g. "Run the eval workflow",
  "Поток запуска тестов").
- `summary` — 1-2 sentences total, in `{lang}`. Frame what the whole flow
  accomplishes for the user.

Names of states, transition `on`/`to` values, and `result_format` field names
are **identifiers** — do not translate them. The diagram and structural fields
keep their original identifiers; only prose is localized.

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

## Step 6 — Walkthrough (only if `eval` provided)

For each state in the flow, write one entry:

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
      "states": [
        {
          "name": "select-eval",
          "one_line": "...",
          "what_the_prompt_asks": "...",
          "inputs": ["title", "description"],
          "outputs": ["outcome", "selected"],
          "transitions": [
            { "on": "done", "to": "[terminal]", "explain": "..." }
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

Omit `walkthrough` entirely if no `eval` was provided. Omit `worker_kind`
and `is_passive` per-state when they don't apply.

## Step 8 — Print the URL

Print the URL clearly to the user:

    http://localhost:7891/explain/{flow}?lang={lang}

If the host environment allows browser-opening commands and the user has not restricted tool use, you may also open it:

- macOS: `open http://localhost:7891/explain/{flow}?lang={lang}`
- Linux: `xdg-open http://localhost:7891/explain/{flow}?lang={lang}`
- Windows: `start http://localhost:7891/explain/{flow}?lang={lang}`

## Pitfall checks

- **Do not paste prompt text verbatim** into `what_the_prompt_asks` when the
  prompt is more than a paragraph. The goal is plain language.
- **Identifiers stay in English**: state names, `on:` values, `result_format`
  field names, `worker.kind` values.
- **Mermaid state IDs can't have hyphens**: replace `-` with `_` in the
  diagram only.
- **Best-effort inputs scan**: a `{{ issue.fields.X }}` in a Jinja `{% if %}`
  branch still counts as an input. List it. Don't try to be exhaustive — a
  prompt that conditionally reads `notes` is OK to list `notes` once.
- **No `walkthrough` without `eval`**: if no eval was provided, the
  `walkthrough` key must be absent from the output, not present-but-empty.
- **Daemon must be up before opening the URL** — if it isn't, the user gets a
  connection-refused error in the browser. Check with `orca_daemon_status` or
  `orca daemon status` in Step 1.
