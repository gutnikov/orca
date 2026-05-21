# Playbook: Explain a Workflow

Generate a plain-language, language-localized explanation of an orca workflow
and open it in the web UI. The output is a single JSON file under
`.orca-state/explanations/{flow}.{lang}.json` that the daemon serves at
`GET /api/explanations/{flow}` and the web app renders at
`http://localhost:7891/explain/{flow}?lang={lang}` (Mermaid state diagram +
per-state cards + optional eval walkthrough).

Audience for the rendered page: a smart non-engineer. Avoid jargon. Translate
the *intent* of each prompt — do not paste prompt text verbatim.

## Required reading (you, the agent — not the user)

- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — workflow YAML structure, `result_format`, template variables.

## When to use this

- The user asks "explain this flow", "show me how X works", "walk me through the run-evals flow", "объясни этот поток на русском", etc.
- The user invokes the playbook by name with a flow argument.

## Inputs

- **`flow`** (required) — the YAML stem under `.orca/`, e.g. `run-evals`.
- **`lang`** (optional, default `en`) — ISO 639-1 code, e.g. `en`, `ru`, `es`, `de`, `fr`.
- **`eval`** (optional) — subdirectory name under `.orca/evals/`. When provided, a "walkthrough" section is added that anchors the explanation in this concrete scenario.

If `flow` is missing, stop and ask. Don't guess from `.orca/` directory listing.

## Output

A single JSON file at `.orca-state/explanations/{flow}.{lang}.json` matching the schema in [Step 7](#step-7--write-the-json). Then open the URL in the user's browser.

---

## Step 1 — Confirm inputs and prerequisites

- `.orca/{flow}.yml` exists. If not, stop with a clear message ("no workflow named X found under .orca/").
- If `eval` provided, `.orca/evals/{eval}/` exists. If not, stop similarly.
- The orca daemon is running. Check via the `orca_daemon_status` MCP tool when available; otherwise do `curl -s http://localhost:7891/api/health` and confirm 200. If down, tell the user to start it (`orca daemon start`) and stop.

## Step 2 — Read the artefacts

Read these files (use the file-reading tools available to you, not `cat`):

- `.orca/{flow}.yml` — the workflow definition.
- For every `state.worker.prompt: path/to.md` entry, read that prompt file (path is relative to `.orca/`).
- For states with inline `prompt: { text: "..." }`, capture the inline string.
- If `eval` provided: `.orca/evals/{eval}/README.md` and any other files in that directory.

If a referenced prompt file is missing, flag it but continue — emit a state with `what_the_prompt_asks` set to "(prompt file missing — could not summarise)" in the target language.

## Step 3 — Derive the structural fields

From the YAML, derive for each state:

- `name` — the state's YAML key (e.g. `select-eval`).
- `worker_kind` — the value of `state.worker.kind` if present (e.g. `claude-code`). Omit field if no `worker` block.
- `is_passive: true` when there is no `worker` block.
- `inputs` — best-effort scan of the prompt template for `{{ issue.fields.X }}` references plus any inputs explicitly described in the prompt's prose. List the field names as `["title", "description", ...]`. **This is best-effort by string scan — note this fact internally; do not promise exhaustiveness.**
- `outputs` — keys from `state.worker.result_format` (if present). For each, the key name only (e.g. `["outcome", "selected"]`).
- `transitions` — from `state.on.{event}: {target_state}` pairs. Each transition is `{on: event, to: target_state, explain: <see Step 4>}`.

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
- Terminal states are: states listed in the workflow's `terminal:` block
  (if present), OR states with no `on:` block, OR states that transition
  to `done`. Add `state --> [*]` lines for each.
- Mermaid identifiers don't allow hyphens — replace `-` with `_` in state
  names *for the diagram only*. Keep the original names in `states[].name`.

## Step 6 — Walkthrough (only if `eval` provided)

For each state in the flow, write one entry:

- `state` — state name (original identifier, not translated).
- `what_happens` — one or two sentences in `{lang}` describing what would
  occur at this state given the eval's scenario.
- `expected_outcome` — short prediction of the outcome enum value or the
  shape of the result, in `{lang}`.

Use the eval's `README.md` and fixtures as context. If you cannot reasonably
predict (e.g. the eval is about prompt quality, not flow behaviour), say so
in `what_happens` — don't fabricate.

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

## Step 8 — Open the URL

Print the URL clearly to the user, then open it in their browser:

- macOS: `open http://localhost:7891/explain/{flow}?lang={lang}`
- Linux: `xdg-open http://localhost:7891/explain/{flow}?lang={lang}`
- Windows: `start http://localhost:7891/explain/{flow}?lang={lang}`

Use the available shell tool. If you cannot open the browser, still print
the URL.

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
  connection-refused error in the browser. Catch it earlier in Step 1.
