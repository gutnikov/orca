export type ExplainStateTransition = {
  on: string
  to: string
  explain: string
}

export type ExplainState = {
  name: string
  one_line: string
  what_the_prompt_asks: string
  inputs: string[]
  outputs: string[]
  transitions: ExplainStateTransition[]
  worker_kind?: string
  is_passive?: boolean
}

export type WalkthroughStep = {
  state: string
  what_happens: string
  expected_outcome: string
}

export type Explanation = {
  flow: string
  language: string
  title: string
  summary: string
  diagram_mermaid: string
  states: ExplainState[]
  walkthrough?: WalkthroughStep[]
  generated_at: string
}

export class ExplanationNotFoundError extends Error {
  hint?: string
  constructor(hint?: string) {
    super("not_found")
    this.name = "ExplanationNotFoundError"
    this.hint = hint
  }
}

export class ExplanationCorruptedError extends Error {
  detail?: string
  constructor(detail?: string) {
    super("corrupted")
    this.name = "ExplanationCorruptedError"
    this.detail = detail
  }
}

export async function loadExplanation(flow: string, lang: string): Promise<Explanation> {
  const url = `/api/explanations/${encodeURIComponent(flow)}?lang=${encodeURIComponent(lang)}`
  const res = await fetch(url)
  if (res.status === 404) {
    const body = (await res.json().catch(() => ({}))) as { hint?: string }
    throw new ExplanationNotFoundError(body.hint)
  }
  if (res.status === 500) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string }
    throw new ExplanationCorruptedError(body.detail)
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as Explanation
}
