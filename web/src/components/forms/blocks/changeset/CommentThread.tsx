import { useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Pencil, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { CommentComposer } from "./CommentComposer"
import type { ReviewComment } from "@/lib/schema"

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
}) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editBody, setEditBody] = useState("")

  return (
    <div className="bg-muted/30 border-y">
      {comments.map((c) => {
        const idx = globalIndexOf(c)
        const isEditing = editingIndex === idx
        const isHighlighted = highlightedIndex === idx
        return (
          <div
            key={idx}
            data-highlight={isHighlighted ? "on" : undefined}
            className={cn(
              "border-l-2 border-primary/50 bg-card mx-3 my-2 rounded-md p-3 group/comment transition-all",
              isHighlighted && "ring-2 ring-primary/40 shadow-md",
            )}
          >
            {isEditing ? (
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
            ) : (
              <div className="flex items-start gap-2">
                <div className="prose prose-sm dark:prose-invert flex-1 max-w-none text-sm">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{c.body}</ReactMarkdown>
                </div>
                <div className="flex gap-1 opacity-0 group-hover/comment:opacity-100 transition-opacity">
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    onClick={() => {
                      setEditingIndex(idx)
                      setEditBody(c.body)
                    }}
                    aria-label="Edit comment"
                  >
                    <Pencil size={12} />
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6 text-destructive"
                    onClick={() => onDelete(idx)}
                    aria-label="Delete comment"
                  >
                    <Trash2 size={12} />
                  </Button>
                </div>
              </div>
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
