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
    <div className="bg-card border rounded-md mx-3 my-2 p-2 space-y-1.5">
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
        className="resize-y text-xs leading-snug min-h-[3rem] px-2 py-1.5 rounded-md"
      />
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">⌘/Ctrl ⏎ save · Esc cancel</span>
        <div className="flex gap-1">
          <Button type="button" size="sm" variant="ghost" onClick={onCancel} className="h-6 px-2 text-[11px] rounded-md">
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={!canSave} onClick={onSave} className="h-6 px-2 text-[11px] rounded-md">
            {saveLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
