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
