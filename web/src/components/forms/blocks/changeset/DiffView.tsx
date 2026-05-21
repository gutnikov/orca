import { useMemo } from "react"
import type { ChangesetFile } from "@/lib/schema"
import { parseUnifiedDiff, hunksToUnifiedRows, hunksToSplitRows } from "./diff-parser"
import type { ViewMode } from "./types"
import { DiffRowView } from "./DiffRowView"
import { rowStyles } from "./diff-viewer-styles"

export function DiffView({
  file,
  mode,
  onAddComment,
}: {
  file: ChangesetFile
  mode: Exclude<ViewMode, "full">
  onAddComment: (side: "old" | "new", line: number) => void
}) {
  const hunks = useMemo(() => parseUnifiedDiff(file.diff), [file.diff])

  if (hunks.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">diff not available</div>
    )
  }

  if (mode === "changes") {
    const rows = hunksToUnifiedRows(hunks)
    return (
      <div className="overflow-x-auto">
        {rows.map((r) => {
          if (r.kind === "hunk-header") {
            return (
              <div key={r.rowKey} className={rowStyles.hunkHeader}>
                {r.header}
              </div>
            )
          }
          const side: "old" | "new" = r.row.type === "removed" ? "old" : "new"
          const line = (r.row.type === "removed" ? r.row.oldLine : r.row.newLine) ?? 0
          return (
            <DiffRowView
              key={r.rowKey}
              row={r.row}
              language={file.language}
              onAddComment={() => onAddComment(side, line)}
            />
          )
        })}
      </div>
    )
  }

  // Split mode
  const rows = hunksToSplitRows(hunks)
  return (
    <div className="grid grid-cols-2 divide-x">
      <div>
        {rows.map((r) => {
          if (r.kind === "hunk-header") return <div key={`L-${r.rowKey}`} className={rowStyles.hunkHeader}>{r.header}</div>
          const left = r.pair.left
          if (!left) {
            return <div key={`L-${r.pair.rowKey}`} className={`${rowStyles.base} ${rowStyles.context}`}><span /><span /><span /><span /></div>
          }
          const line = left.oldLine ?? 0
          return (
            <DiffRowView
              key={`L-${r.pair.rowKey}`}
              row={left}
              language={file.language}
              pairedWith={r.pair.right ?? undefined}
              onAddComment={() => onAddComment("old", line)}
            />
          )
        })}
      </div>
      <div>
        {rows.map((r) => {
          if (r.kind === "hunk-header") return <div key={`R-${r.rowKey}`} className={rowStyles.hunkHeader}>{r.header}</div>
          const right = r.pair.right
          if (!right) {
            return <div key={`R-${r.pair.rowKey}`} className={`${rowStyles.base} ${rowStyles.context}`}><span /><span /><span /><span /></div>
          }
          const line = right.newLine ?? 0
          return (
            <DiffRowView
              key={`R-${r.pair.rowKey}`}
              row={right}
              language={file.language}
              pairedWith={r.pair.left ?? undefined}
              onAddComment={() => onAddComment("new", line)}
            />
          )
        })}
      </div>
    </div>
  )
}
