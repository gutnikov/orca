import { useMemo } from "react"
import type { ChangesetFile, ReviewComment } from "./types"
import { parseUnifiedDiff, hunksToUnifiedRows, hunksToSplitRows } from "./diff-parser"
import type { ViewMode } from "./types"
import { DiffRowView } from "./DiffRowView"
import { rowStyles } from "./diff-viewer-styles"
import { CommentThread } from "./CommentThread"

// InlineComment: a comment the user places on a specific file+line during review.
// This type will be promoted to a shared useDraftComments.ts in a later task.
export interface InlineComment {
  file: string
  line: number | null
  body: string
}

type CommentSide = "old" | "new"

export type DiffViewOverlay = {
  commentsForLine: (file: string, side: CommentSide, line: number) => ReviewComment[]
  draftForLine: (file: string, side: CommentSide, line: number) => string | undefined
  globalIndexOf: (c: ReviewComment) => number
  onOpenDraft: (side: CommentSide, line: number) => void
  onUpdateDraft: (side: CommentSide, line: number, body: string) => void
  onSaveDraft: (side: CommentSide, line: number) => void
  onCloseDraft: (side: CommentSide, line: number) => void
  onEditComment: (index: number, body: string) => void
  onDeleteComment: (index: number) => void
  highlightedCommentIndex: number | null
}

export function DiffView({
  file,
  mode,
  overlay,
}: {
  file: ChangesetFile
  mode: Exclude<ViewMode, "full">
  overlay: DiffViewOverlay
}) {
  const hunks = useMemo(() => parseUnifiedDiff(file.diff), [file.diff])

  if (hunks.length === 0) {
    return <div className="p-6 text-center text-sm text-muted-foreground">diff not available</div>
  }

  const renderOverlay = (side: CommentSide, line: number) => {
    const comments = overlay.commentsForLine(file.path, side, line)
    const draft = overlay.draftForLine(file.path, side, line)
    if (comments.length === 0 && draft === undefined) return null
    return (
      <CommentThread
        comments={comments}
        globalIndexOf={overlay.globalIndexOf}
        onEdit={overlay.onEditComment}
        onDelete={overlay.onDeleteComment}
        draft={draft}
        onDraftChange={(v) => overlay.onUpdateDraft(side, line, v)}
        onDraftSave={() => overlay.onSaveDraft(side, line)}
        onDraftCancel={() => overlay.onCloseDraft(side, line)}
        highlightedIndex={overlay.highlightedCommentIndex}
      />
    )
  }

  if (mode === "changes") {
    const rows = hunksToUnifiedRows(hunks)
    return (
      <div className="overflow-x-auto w-full">
        {rows.map((r) => {
          if (r.kind === "hunk-header") {
            return <div key={r.rowKey} className={rowStyles.hunkHeader}>{r.header}</div>
          }
          const side: CommentSide = r.row.type === "removed" ? "old" : "new"
          const line = (r.row.type === "removed" ? r.row.oldLine : r.row.newLine) ?? 0
          return (
            <div key={r.rowKey}>
              <DiffRowView
                row={r.row}
                language={file.language}
                onAddComment={() => overlay.onOpenDraft(side, line)}
              />
              {renderOverlay(side, line)}
            </div>
          )
        })}
      </div>
    )
  }

  const rows = hunksToSplitRows(hunks)
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] divide-x w-full">
      <div className="overflow-x-auto">
        {rows.map((r) => {
          if (r.kind === "hunk-header") return <div key={`L-${r.rowKey}`} className={rowStyles.hunkHeader}>{r.header}</div>
          const left = r.pair.left
          if (!left) return <div key={`L-${r.pair.rowKey}`} className={`${rowStyles.base} ${rowStyles.context}`}><span /><span /><span /><span /></div>
          const line = left.oldLine ?? 0
          return (
            <div key={`L-${r.pair.rowKey}`}>
              <DiffRowView
                row={left}
                language={file.language}
                pairedWith={r.pair.right ?? undefined}
                onAddComment={() => overlay.onOpenDraft("old", line)}
              />
              {renderOverlay("old", line)}
            </div>
          )
        })}
      </div>
      <div className="overflow-x-auto">
        {rows.map((r) => {
          if (r.kind === "hunk-header") return <div key={`R-${r.rowKey}`} className={rowStyles.hunkHeader}>{r.header}</div>
          const right = r.pair.right
          if (!right) return <div key={`R-${r.pair.rowKey}`} className={`${rowStyles.base} ${rowStyles.context}`}><span /><span /><span /><span /></div>
          const line = right.newLine ?? 0
          return (
            <div key={`R-${r.pair.rowKey}`}>
              <DiffRowView
                row={right}
                language={file.language}
                pairedWith={r.pair.left ?? undefined}
                onAddComment={() => overlay.onOpenDraft("new", line)}
              />
              {renderOverlay("new", line)}
            </div>
          )
        })}
      </div>
    </div>
  )
}
