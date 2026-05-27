import { useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

type Mode = "write" | "preview"

export function CommentComposer({
  value,
  onChange,
  onSave,
  onCancel,
  autoFocus = true,
  saveLabel = "Save",
}: {
  value: string
  onChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
  autoFocus?: boolean
  saveLabel?: string
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [mode, setMode] = useState<Mode>("write")

  useEffect(() => {
    if (autoFocus && mode === "write") ref.current?.focus()
  }, [autoFocus, mode])

  const canSave = value.trim().length > 0

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-md mx-3 my-2">
      <div className="flex border-b border-[var(--border)] bg-[var(--subtle)] rounded-t-md px-1.5 pt-1.5 gap-1">
        {(["write", "preview"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "px-3 py-1 text-[12px] rounded-t-md transition-colors capitalize",
              mode === m
                ? "bg-[var(--surface)] text-[var(--fg)] border border-[var(--border)] border-b-0 -mb-px font-medium"
                : "text-[var(--fg-muted)] hover:text-[var(--fg)]",
            )}
          >
            {m}
          </button>
        ))}
      </div>
      <div className="p-2 space-y-1.5">
        {mode === "write" ? (
          <Textarea
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canSave) {
                e.preventDefault()
                onSave()
              } else if (e.key === "Escape") {
                e.preventDefault()
                onCancel()
              }
            }}
            rows={2}
            placeholder="Leave a comment"
            className="resize-y text-[13px] leading-snug min-h-[3rem] px-2 py-1.5 rounded-md font-mono"
          />
        ) : (
          <div className="min-h-[3rem] px-2 py-1.5 text-[13px] text-[var(--fg)]">
            {value.trim() ? (
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
              </div>
            ) : (
              <span className="text-[var(--fg-muted)] italic">Nothing to preview.</span>
            )}
          </div>
        )}
        <div className="flex items-center justify-between pt-1">
          <span className="text-[10.5px] text-[var(--fg-subtle)]">
            ⌘/Ctrl ⏎ save · Esc cancel · Markdown supported
          </span>
          <div className="flex gap-1.5">
            <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              variant="primary"
              disabled={!canSave}
              onClick={onSave}
            >
              {saveLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
