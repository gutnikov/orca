export type ViewMode = "changes" | "split" | "full"

export type RowType = "added" | "removed" | "context" | "hunk-header"

export type Hunk = {
  oldStart: number
  oldLines: number
  newStart: number
  newLines: number
  header: string
  rows: HunkRow[]
}

export type HunkRow = {
  type: "added" | "removed" | "context"
  oldLine: number | null
  newLine: number | null
  text: string
}

export type DiffRow =
  | { kind: "row"; row: HunkRow; rowKey: string }
  | { kind: "hunk-header"; header: string; rowKey: string }

export type SplitRowPair = {
  rowKey: string
  left: HunkRow | null
  right: HunkRow | null
}

export type SplitDiffRow =
  | { kind: "pair"; pair: SplitRowPair }
  | { kind: "hunk-header"; header: string; rowKey: string }

export type DraftKey = string

export function draftKey(file: string, side: "old" | "new", line: number): DraftKey {
  return `${file}:${side}:${line}`
}

// ChangesetFile: a single file in a diff changeset
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

// ReviewComment: an inline comment attached to a specific file+line
export type ReviewComment = {
  // Client-side stable id, used to correlate a comment with its agent
  // question/answer record. Not the same as the global array index.
  id: string
  file: string
  line: number
  side: "old" | "new"
  body: string
}
