import { ChevronsDown, ChevronsUp, MessageSquare } from "lucide-react"
import { Popover } from "radix-ui"
import { Button } from "@/components/ui/button"
import type { ReviewComment } from "@/lib/schema"

export function ReviewToolbar({
  fileCount,
  comments,
  onExpandAll,
  onCollapseAll,
  onJumpToComment,
}: {
  fileCount: number
  comments: ReviewComment[]
  onExpandAll: () => void
  onCollapseAll: () => void
  onJumpToComment: (index: number) => void
}) {
  return (
    <div className="flex items-center gap-2 py-2">
      <div className="text-xs text-muted-foreground font-mono mr-auto">
        {fileCount} file{fileCount === 1 ? "" : "s"} changed
      </div>
      <Button type="button" size="sm" variant="ghost" onClick={onExpandAll}>
        <ChevronsDown size={14} className="mr-1" /> Expand all
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onCollapseAll}>
        <ChevronsUp size={14} className="mr-1" /> Collapse all
      </Button>
      <Popover.Root>
        <Popover.Trigger asChild>
          <Button type="button" size="sm" variant="outline" disabled={comments.length === 0}>
            <MessageSquare size={14} className="mr-1" />
            {comments.length} comment{comments.length === 1 ? "" : "s"}
          </Button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="end"
            sideOffset={6}
            className="z-50 w-[320px] rounded-lg border bg-popover text-popover-foreground shadow-lg p-1.5"
          >
            <ul className="max-h-[60vh] overflow-y-auto space-y-0.5">
              {comments.map((c, i) => (
                <li key={i}>
                  <button
                    type="button"
                    onClick={() => onJumpToComment(i)}
                    className="w-full text-left rounded-md px-2 py-1.5 hover:bg-muted/60 transition-colors"
                  >
                    <div className="text-[11px] font-mono text-muted-foreground truncate">
                      {c.file}:{c.line} · {c.side}
                    </div>
                    <div className="text-sm truncate">{c.body}</div>
                  </button>
                </li>
              ))}
            </ul>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  )
}
