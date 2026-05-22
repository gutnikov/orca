import { useMemo, useRef } from "react"
import { useController, type Control } from "react-hook-form"
import type { FormBlock, ReviewComment, ChangesetFile } from "@/lib/schema"
import { useChangesetState } from "./changeset/useChangesetState"
import { FileCard } from "./changeset/FileCard"
import { DiffView } from "./changeset/DiffView"
import { FullFileView } from "./changeset/FullFileView"
import { FileTreeSidebar } from "./changeset/FileTreeSidebar"
import { ReviewToolbar } from "./changeset/ReviewToolbar"

type Block = Extract<FormBlock, { kind: "changeset" }>

export default function ChangesetBlock({
  block,
  control,
  storageKeyPrefix,
}: {
  block: Block
  control: Control<Record<string, unknown>>
  /** Provided by FormPage; we suffix the block's name onto it. */
  storageKeyPrefix?: string | null
}) {
  const { field } = useController<Record<string, unknown>, string>({
    name: block.name,
    control,
    defaultValue: [] as ReviewComment[],
    rules: block.require_comment
      ? { validate: (v) => (Array.isArray(v) && v.length > 0) || "comment_required" }
      : undefined,
  })

  const storageKey = storageKeyPrefix ? `${storageKeyPrefix}:changeset:${block.name}` : null

  const state = useChangesetState({
    initialComments: (field.value as ReviewComment[]) ?? [],
    onChange: (next) => field.onChange(next),
    filePaths: block.files.map((f: ChangesetFile) => f.path),
    storageKey,
  })

  const globalIndexOf = useMemo(() => {
    const refMap = new Map<ReviewComment, number>()
    state.comments.forEach((c, i) => refMap.set(c, i))
    return (c: ReviewComment) => refMap.get(c) ?? -1
  }, [state.comments])

  const containerRef = useRef<HTMLDivElement>(null)

  const jumpToFile = (path: string) => {
    if (state.collapsed.has(path)) state.toggleCollapse(path)
    requestAnimationFrame(() => {
      const el = containerRef.current?.querySelector(`[data-path="${CSS.escape(path)}"]`)
      if (el instanceof HTMLElement) {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
      }
    })
  }

  const jumpToComment = (index: number) => {
    const c = state.comments[index]
    if (!c) return
    if (state.collapsed.has(c.file)) state.toggleCollapse(c.file)
    requestAnimationFrame(() => {
      const el = containerRef.current?.querySelector(`[data-path="${CSS.escape(c.file)}"]`)
      if (el instanceof HTMLElement) {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
        setTimeout(() => state.flashComment(index), 250)
      }
    })
  }

  return (
    <div className="-mx-6 sm:-mx-12 px-6 sm:px-12">
      <div className="flex gap-6 items-start">
        <FileTreeSidebar
          files={block.files}
          commentCountFor={state.commentCountForFile}
          onSelectFile={jumpToFile}
        />
        <div ref={containerRef} className="flex-1 min-w-0">
          {block.require_comment && state.comments.length === 0 ? (
            <div className="text-[11px] text-muted-foreground italic">
              At least one comment is required.
            </div>
          ) : null}
          <ReviewToolbar
            fileCount={block.files.length}
            comments={state.comments}
            onExpandAll={state.expandAll}
            onCollapseAll={state.collapseAll}
            onJumpToComment={jumpToComment}
          />
          <div className="space-y-3">
            {block.files.map((file: ChangesetFile) => (
              <FileCard
                key={file.path}
                file={file}
                collapsed={state.collapsed.has(file.path)}
                onToggleCollapse={() => state.toggleCollapse(file.path)}
                viewMode={state.viewMode.get(file.path) ?? "changes"}
                onSetMode={(m) => state.setFileMode(file.path, m)}
                commentCount={state.commentCountForFile(file.path)}
              >
                {(() => {
                  const fileMode = state.viewMode.get(file.path) ?? "changes"
                  const overlay = {
                    commentsForLine: state.commentsForLine,
                    draftForLine: state.draftForLine,
                    globalIndexOf,
                    onOpenDraft: (side: "old" | "new", line: number) => state.openDraft(file.path, side, line),
                    onUpdateDraft: (side: "old" | "new", line: number, body: string) => state.updateDraft(file.path, side, line, body),
                    onSaveDraft: (side: "old" | "new", line: number) => state.saveDraft(file.path, side, line),
                    onCloseDraft: (side: "old" | "new", line: number) => state.closeDraft(file.path, side, line),
                    onEditComment: state.editComment,
                    onDeleteComment: state.deleteComment,
                    highlightedCommentIndex: state.highlightedCommentIndex,
                  }
                  return fileMode === "full" ? (
                    <FullFileView file={file} overlay={overlay} />
                  ) : (
                    <DiffView
                      file={file}
                      mode={fileMode as "changes" | "split"}
                      overlay={overlay}
                    />
                  )
                })()}
              </FileCard>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
