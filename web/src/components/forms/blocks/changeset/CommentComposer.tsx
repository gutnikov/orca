import { useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

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
  useEffect(() => {
    if (autoFocus) ref.current?.focus()
  }, [autoFocus])

  const canSave = value.trim().length > 0

  return (
    <div className="border-l-2 border-primary/40 bg-card mx-3 my-2 rounded-md p-3 space-y-2">
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
        rows={3}
        placeholder="Leave a comment"
        className="resize-y text-sm"
      />
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">⌘/Ctrl ⏎ to save · Esc to cancel</span>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={!canSave} onClick={onSave}>
            {saveLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
