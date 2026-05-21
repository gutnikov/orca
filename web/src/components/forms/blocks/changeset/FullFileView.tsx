import { useMemo } from "react"
import { Highlight, themes, type Language } from "prism-react-renderer"
import { MessageSquarePlus } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ChangesetFile } from "@/lib/schema"
import { parseUnifiedDiff } from "./diff-parser"
import { CommentThread } from "./CommentThread"
import { rowStyles } from "./diff-viewer-styles"
import type { DiffViewOverlay } from "./DiffView"
import { useIsDark } from "./useIsDark"

export function FullFileView({
  file,
  overlay,
}: {
  file: ChangesetFile
  overlay: DiffViewOverlay
}) {
  const dark = useIsDark()
  const newContent = file.new_content ?? ""
  const lines = useMemo(() => newContent.split("\n"), [newContent])
  const addedLineSet = useMemo(() => {
    const hunks = parseUnifiedDiff(file.diff)
    const set = new Set<number>()
    for (const h of hunks) for (const r of h.rows) if (r.type === "added" && r.newLine !== null) set.add(r.newLine)
    return set
  }, [file.diff])

  if (typeof file.new_content !== "string") {
    return <div className="p-6 text-center text-sm text-muted-foreground">Full view requires new_content</div>
  }

  return (
    <div className="overflow-x-auto">
      <Highlight code={newContent} language={(file.language ?? "tsx") as Language} theme={dark ? themes.vsDark : themes.github}>
        {({ tokens, getTokenProps }) => (
          <>
            {tokens.map((tokenLine, i) => {
              const lineNumber = i + 1
              const isAdded = addedLineSet.has(lineNumber)
              const tint = isAdded ? rowStyles.added : rowStyles.context

              const comments = overlay.commentsForLine(file.path, "new", lineNumber)
              const draft = overlay.draftForLine(file.path, "new", lineNumber)

              return (
                <div key={i}>
                  <div
                    className={cn(
                      "group/row grid gap-0 font-mono text-[12px] leading-5 min-h-5 grid-cols-[3rem_2rem_1fr]",
                      tint,
                    )}
                  >
                    <span className={rowStyles.gutterNumber}>{lineNumber}</span>
                    <span className={cn(rowStyles.gutterSign, "relative")}>
                      <button
                        type="button"
                        onClick={() => overlay.onOpenDraft("new", lineNumber)}
                        className="absolute inset-0 flex items-center justify-center opacity-0 group-hover/row:opacity-100 transition-opacity text-primary hover:bg-primary/10 rounded"
                        aria-label="Add comment"
                      >
                        <MessageSquarePlus size={12} />
                      </button>
                      <span className="opacity-100 group-hover/row:opacity-0 transition-opacity pointer-events-none">
                        {isAdded ? "+" : ""}
                      </span>
                    </span>
                    <span className={rowStyles.content}>
                      {tokenLine.length === 0 ? (
                        <span>{lines[i] ?? ""}</span>
                      ) : (
                        tokenLine.map((t, j) => <span key={j} {...getTokenProps({ token: t })} />)
                      )}
                    </span>
                  </div>
                  {comments.length > 0 || draft !== undefined ? (
                    <CommentThread
                      comments={comments}
                      globalIndexOf={overlay.globalIndexOf}
                      onEdit={overlay.onEditComment}
                      onDelete={overlay.onDeleteComment}
                      draft={draft}
                      onDraftChange={(v) => overlay.onUpdateDraft("new", lineNumber, v)}
                      onDraftSave={() => overlay.onSaveDraft("new", lineNumber)}
                      onDraftCancel={() => overlay.onCloseDraft("new", lineNumber)}
                      highlightedIndex={overlay.highlightedCommentIndex}
                    />
                  ) : null}
                </div>
              )
            })}
          </>
        )}
      </Highlight>
    </div>
  )
}
