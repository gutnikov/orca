import type { Explanation } from "@/lib/explain"

export const demoExplanation: Explanation = {
  flow: "run-evals",
  language: "en",
  title: "Run an eval against a workflow",
  summary:
    "This single-step flow scans the .orca/evals/ directory, asks the user to pick one via a web form, and records the choice so the run can proceed against it.",
  diagram_mermaid: [
    "stateDiagram-v2",
    "    [*] --> select_eval",
    "    select_eval --> [*] : done",
  ].join("\n"),
  states: [
    {
      name: "select-eval",
      one_line: "Discover available evals and ask the user to pick one.",
      what_the_prompt_asks:
        "Scan the .orca/evals/ folder for subdirectories. If none exist, emit an outcome of 'done' with selected='none' and stop. Otherwise, emit a 'waiting' outcome carrying a web form that lists the discovered evals as a select field, then wait for the user's submission.",
      inputs: ["title (ignored)", "description (ignored)"],
      outputs: ["outcome", "selected"],
      transitions: [
        { on: "done", to: "[terminal]", explain: "Always: this is a single-state flow." },
      ],
      worker_kind: "claude-code",
      is_passive: false,
    },
  ],
  walkthrough: [
    {
      state: "select-eval",
      what_happens: "The worker lists three subdirectories (auth-flow, diff-rendering, scoping-quality), shows them in a picker form, and waits.",
      expected_outcome: "outcome='done', selected='auth-flow' (or whichever you pick).",
    },
  ],
  generated_at: "2026-05-21T11:00:00.000Z",
}
