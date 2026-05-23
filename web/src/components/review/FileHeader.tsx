import { ChevronDown, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { ChangesetFile, FileStatus } from "./types"
import type { ViewMode } from "./types"

const STATUS_LABEL: Record<FileStatus, string> = {
  added: "ADDED",
  modified: "MODIFIED",
  deleted: "DELETED",
  renamed: "RENAMED",
}

const STATUS_TINT: Record<FileStatus, string> = {
  added: "bg-[oklch(0.92_0.05_150)] text-[oklch(0.35_0.15_150)] dark:bg-[oklch(0.25_0.08_150)] dark:text-[oklch(0.85_0.12_150)]",
  modified: "bg-[oklch(0.92_0.05_260)] text-[oklch(0.40_0.18_260)] dark:bg-[oklch(0.25_0.08_260)] dark:text-[oklch(0.85_0.12_260)]",
  deleted: "bg-[oklch(0.93_0.05_30)] text-[oklch(0.45_0.20_30)] dark:bg-[oklch(0.25_0.08_30)] dark:text-[oklch(0.85_0.14_30)]",
  renamed: "bg-muted text-muted-foreground",
}

const MODES: { value: ViewMode; label: string }[] = [
  { value: "changes", label: "Changes" },
  { value: "split", label: "Split" },
  { value: "full", label: "Full" },
]

export function FileHeader({
  file,
  collapsed,
  onToggleCollapse,
  viewMode,
  onSetMode,
  fullEnabled,
  commentCount,
}: {
  file: ChangesetFile
  collapsed: boolean
  onToggleCollapse: () => void
  viewMode: ViewMode
  onSetMode: (m: ViewMode) => void
  fullEnabled: boolean
  commentCount: number
}) {
  const segments = file.path.split("/")
  const filename = segments.at(-1) ?? file.path
  const dir = segments.slice(0, -1).join("/")
  const dirDisplay = dir ? `${dir}/` : ""

  return (
    <div
      className={cn(
        "sticky top-0 z-10 flex items-center gap-3 px-4 py-3",
        "bg-card/85 backdrop-blur-sm border-b",
      )}
    >
      <button
        type="button"
        onClick={onToggleCollapse}
        aria-label={collapsed ? "Expand file" : "Collapse file"}
        className="text-muted-foreground hover:text-foreground transition-colors"
      >
        {collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
      </button>

      <span
        className={cn(
          "rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wider",
          STATUS_TINT[file.status],
        )}
      >
        {STATUS_LABEL[file.status]}
      </span>

      <div className="flex-1 min-w-0 truncate font-mono text-sm">
        <span className="text-muted-foreground">{dirDisplay}</span>
        <span className="font-semibold">{filename}</span>
        {file.status === "renamed" && file.old_path ? (
          <span className="text-muted-foreground text-xs ml-2">← {file.old_path}</span>
        ) : null}
      </div>

      <div className="flex items-center gap-3 text-xs font-mono">
        <span className="text-[oklch(0.55_0.18_150)]">+{file.additions}</span>
        <span className="text-[oklch(0.55_0.20_30)]">−{file.deletions}</span>
      </div>

      {commentCount > 0 ? (
        <span className="rounded-full bg-primary/10 text-primary px-2 py-0.5 text-[10px] font-medium">
          {commentCount}
        </span>
      ) : null}

      <div className="inline-flex rounded-md border bg-muted/50 p-0.5">
        {MODES.map((m) => {
          const disabled = m.value === "full" && !fullEnabled
          const active = viewMode === m.value
          return (
            <Button
              key={m.value}
              type="button"
              size="sm"
              variant={active ? "secondary" : "ghost"}
              disabled={disabled}
              onClick={() => onSetMode(m.value)}
              className="h-6 px-2 text-[11px]"
              title={disabled ? "Full view requires new_content" : undefined}
            >
              {m.label}
            </Button>
          )
        })}
      </div>
    </div>
  )
}
