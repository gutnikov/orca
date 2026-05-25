import { useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Pencil, Trash2, Sparkles, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { CommentComposer } from "./CommentComposer"
import type { ReviewComment } from "./types"

export function CommentThread({
  comments,
  globalIndexOf,
  onEdit,
  onDelete,
  draft,
  onDraftChange,
  onDraftSave,
  onDraftCancel,
  highlightedIndex,
  questionForComment,
  onAskQuestion,
}: {
  comments: ReviewComment[]
  globalIndexOf: (c: ReviewComment) => number
  onEdit: (index: number, body: string) => void
  onDelete: (index: number) => void
  draft: string | undefined
  onDraftChange: (v: string) => void
  onDraftSave: () => void
  onDraftCancel: () => void
  highlightedIndex?: number | null
  questionForComment?: (commentId: string) => { pending: boolean; answer: string | null } | undefined
  onAskQuestion?: (comment: ReviewComment) => void
}) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editBody, setEditBody] = useState("")

  return (
    <div className="bg-muted/20 border-y py-1">
      {comments.map((c) => {
        const idx = globalIndexOf(c)
        const isEditing = editingIndex === idx
        const isHighlighted = highlightedIndex === idx
        const question = questionForComment?.(c.id)
        const askEnabled = onAskQuestion !== undefined && c.body.trim().length > 0
        // Asking is "in flight" when we have a tracked question with no answer yet.
        // The optimistic record (questionId="") also marks pending.
        const pending = question !== undefined && question.answer === null
        const answered = question !== undefined && question.answer !== null
        return (
          <div
            key={idx}
            data-highlight={isHighlighted ? "on" : undefined}
            className={cn(
              "bg-card border border-border/60 shadow-xs mx-3 my-1.5 rounded-md group/comment transition-all",
              isHighlighted && "ring-2 ring-primary/40 shadow-md",
            )}
          >
            {isEditing ? (
              <div className="p-1">
                <CommentComposer
                  value={editBody}
                  onChange={setEditBody}
                  onSave={() => {
                    onEdit(idx, editBody)
                    setEditingIndex(null)
                  }}
                  onCancel={() => setEditingIndex(null)}
                  saveLabel="Update"
                />
              </div>
            ) : (
              <>
                <div className="px-3 pt-1.5 pb-0 flex items-center justify-between text-[10px] text-muted-foreground font-mono">
                  <span className="truncate">
                    {c.file}
                    <span className="text-muted-foreground/60">:{c.line}</span>
                  </span>
                  <div className="flex gap-0.5 opacity-0 group-hover/comment:opacity-100 transition-opacity shrink-0">
                    {askEnabled && question === undefined ? (
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-5 w-5 text-primary"
                        onClick={() => onAskQuestion(c)}
                        aria-label="Ask agent"
                        title="Ask agent to answer this comment"
                      >
                        <Sparkles size={11} />
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="h-5 w-5"
                      onClick={() => {
                        setEditingIndex(idx)
                        setEditBody(c.body)
                      }}
                      aria-label="Edit comment"
                    >
                      <Pencil size={11} />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="h-5 w-5 text-destructive"
                      onClick={() => onDelete(idx)}
                      aria-label="Delete comment"
                    >
                      <Trash2 size={11} />
                    </Button>
                  </div>
                </div>
                <div className="prose prose-sm dark:prose-invert max-w-none text-sm px-3 pb-2 pt-0.5 [&_p]:my-1 [&_pre]:my-1 [&_ul]:my-1">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{c.body}</ReactMarkdown>
                </div>
                {pending ? (
                  <div className="mx-3 mb-2 mt-0 flex items-center gap-1.5 text-[11px] text-muted-foreground border-t border-border/40 pt-1.5">
                    <Loader2 size={11} className="animate-spin" />
                    <span>Orca is thinking…</span>
                  </div>
                ) : null}
                {answered ? (
                  <div className="mx-3 mb-2 mt-0 border-t border-border/40 pt-1.5">
                    <div className="flex items-center gap-1.5 text-[10px] text-primary font-mono mb-1">
                      <Sparkles size={10} />
                      <span>Orca</span>
                    </div>
                    <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_p]:my-1 [&_pre]:my-1 [&_ul]:my-1">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.answer ?? ""}</ReactMarkdown>
                    </div>
                  </div>
                ) : null}
              </>
            )}
          </div>
        )
      })}
      {draft !== undefined ? (
        <CommentComposer
          value={draft}
          onChange={onDraftChange}
          onSave={onDraftSave}
          onCancel={onDraftCancel}
        />
      ) : null}
    </div>
  )
}
