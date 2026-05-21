export type FieldType =
  | "text"
  | "email"
  | "password"
  | "number"
  | "checkbox"
  | "select"
  | "textarea"
  | "date"

export type FieldBlock = {
  kind: "field"
  name: string
  type: FieldType
  label: string
  required?: boolean
  default?: unknown
  help?: string
  placeholder?: string
  pattern?: string
  min?: number
  max?: number
  step?: number
  rows?: number
  options?: { value: string; label: string }[]
}

export type FileStatus = "added" | "modified" | "deleted" | "renamed"

export type ChangesetFile = {
  path: string
  status: FileStatus
  old_path?: string
  language?: string
  additions: number
  deletions: number
  diff: string
  old_content?: string
  new_content?: string
}

export type ReviewComment = {
  file: string
  line: number
  side: "old" | "new"
  body: string
}

export type FormBlock =
  | { kind: "markdown"; content: string }
  | { kind: "code"; language?: string; content: string }
  | { kind: "diff"; filename?: string; content: string }
  | { kind: "changeset"; name: string; files: ChangesetFile[]; require_comment?: boolean }
  | FieldBlock

export type FormStep = {
  title?: string
  blocks: FormBlock[]
}

export type FormSchema = {
  title: string
  description?: string
  submit_label?: string
  cancel_label?: string
  steps: FormStep[]
}

export type FormContext = {
  state: string
  reason: string
  started_waiting_at: string
}

export type FormResponse = {
  run_id: string
  issue_id: string
  schema: FormSchema
  context: FormContext
}

export type PendingListEntry = {
  run_id: string
  issue_id: string
  state: string
  title: string
  started_waiting_at: string
  url: string
}

export type SubmitEnvelope = { values: Record<string, unknown> } | { cancelled: true }

export function schemaToDefaults(schema: FormSchema): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const step of schema.steps) {
    for (const block of step.blocks) {
      if (block.kind !== "field") continue
      if (block.default !== undefined) {
        out[block.name] = block.default
      } else if (block.type === "checkbox") {
        out[block.name] = false
      } else if (block.type === "number") {
        out[block.name] = ""
      } else {
        out[block.name] = ""
      }
    }
  }
  return out
}

export function stepFieldNames(step: FormStep): string[] {
  return step.blocks.filter((b): b is FieldBlock => b.kind === "field").map((b) => b.name)
}
