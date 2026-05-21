---
name: orca-workflow-explain
description: Use when the user wants a plain-language explanation of an orca workflow — its states, prompts, transitions — rendered in the web UI with a Mermaid state diagram. Triggers on "explain the X flow", "show me how X works", "walk me through this workflow", "describe the X workflow", "объясни этот поток", "explica el flujo X". Accepts a language parameter (ISO 639-1 codes: en, ru, es, de, fr, …) and an optional eval name to anchor the explanation in a concrete scenario.
---

# Explain an orca workflow in the web UI

You are an explainer agent. Read a workflow's YAML + prompts (optionally an eval),
write a localized plain-language explanation to `.orca-state/explanations/{flow}.{lang}.json`,
then open `http://localhost:{browser_port}/explain/{flow}?lang={lang}` in the user's browser
— the `browser_port` is the TCP port reported by `orca_daemon_status` (usually `7891`).

## Required reading

- `src/orca/playbooks/orca-workflow-explain.md` — the procedural playbook (read this end to end before doing anything).

## Inputs

- **flow** (required) — the workflow filename stem under `.orca/`. Ask if missing.
- **lang** (optional, default `en`) — ISO 639-1 code.
- **eval** (optional) — subdirectory name under `.orca/evals/`.

## Tone

Audience is a smart non-engineer. Plain language, no jargon. Translate prompt
intent, do not paste prompt text verbatim. State names and identifiers stay in
English.

Follow the playbook for the full procedure.
