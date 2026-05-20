import type { FormResponse, PendingListEntry, SubmitEnvelope } from "./schema"

export class FormNotFoundError extends Error {
  constructor() {
    super("not_found")
    this.name = "FormNotFoundError"
  }
}

export class FormExpiredError extends Error {
  constructor() {
    super("worker_not_waiting")
    this.name = "FormExpiredError"
  }
}

export class FormAlreadySubmittedError extends Error {
  constructor() {
    super("already_submitted")
    this.name = "FormAlreadySubmittedError"
  }
}

export class ValidationError extends Error {
  fieldErrors: Record<string, string>
  constructor(fieldErrors: Record<string, string>) {
    super("validation_failed")
    this.name = "ValidationError"
    this.fieldErrors = fieldErrors
  }
}

export type FormLoadResult = FormResponse | { alreadySubmitted: true }

export async function loadForm(runId: string, issueId: string): Promise<FormLoadResult> {
  const url = `/api/runs/${encodeURIComponent(runId)}/forms/${encodeURIComponent(issueId)}`
  const res = await fetch(url)
  if (res.status === 404) throw new FormNotFoundError()
  if (res.status === 410) return { alreadySubmitted: true }
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as FormResponse
}

export async function submitForm(
  runId: string,
  issueId: string,
  envelope: SubmitEnvelope,
): Promise<void> {
  const url = `/api/runs/${encodeURIComponent(runId)}/forms/${encodeURIComponent(issueId)}/submit`
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(envelope),
  })
  if (res.status === 409) throw new FormExpiredError()
  if (res.status === 410) throw new FormAlreadySubmittedError()
  if (res.status === 422) {
    const body = (await res.json()) as { field_errors: Record<string, string> }
    throw new ValidationError(body.field_errors ?? {})
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

export async function listPending(): Promise<PendingListEntry[]> {
  const res = await fetch("/api/forms/pending")
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const body = (await res.json()) as { pending: PendingListEntry[] }
  return body.pending
}
