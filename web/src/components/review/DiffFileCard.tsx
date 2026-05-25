import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"

import { cn } from "@/lib/utils"

import { DiffView, type DiffViewOverlay } from "./DiffView"
import { FullFileView } from "./FullFileView"
import type { ChangesetFile, FileStatus, ViewMode } from "./types"

const STATUS_LABEL: Record<FileStatus, string> = {
  added: "Added",
  modified: "Modified",
  deleted: "Deleted",
  renamed: "Renamed",
}

const STATUS_DOT: Record<FileStatus, string> = {
  added: "bg-[oklch(0.65_0.18_150)]",
  modified: "bg-[oklch(0.55_0.20_260)]",
  deleted: "bg-[oklch(0.60_0.22_30)]",
  renamed: "bg-muted-foreground",
}

interface DiffFileCardProps {
  file: ChangesetFile
  overlay: DiffViewOverlay
  collapsed: boolean
  onToggleCollapsed: () => void
  commentCount: number
  /** Anchor id used for sidebar click-to-scroll. */
  anchorId: string
}

const MODE_LABEL: Record<ViewMode, string> = {
  changes: "Unified",
  split: "Split",
  full: "Full file",
}

export function DiffFileCard({
  file,
  overlay,
  collapsed,
  onToggleCollapsed,
  commentCount,
  anchorId,
}: DiffFileCardProps) {
  const [mode, setMode] = useState<ViewMode>("changes")
  const hasNewContent = typeof file.new_content === "string" && file.new_content.length > 0
  // Full mode needs new_content (the post-change file contents) to render the
  // whole file with added-line highlights. If absent (deleted files, binary
  // files, or fetch failures), the Full button is disabled with a tooltip.

  return (
    <div id={anchorId} className="rounded-lg border border-border bg-card overflow-hidden scroll-mt-6">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/30">
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
          aria-label={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
        </button>
        <span
          className={cn("h-1.5 w-1.5 rounded-full shrink-0", STATUS_DOT[file.status])}
          aria-label={STATUS_LABEL[file.status]}
        />
        <span className="font-mono text-[13px] font-semibold truncate" title={file.path}>
          {file.path}
        </span>
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {(file.additions || file.deletions) ? (
            <span className="font-mono text-[11px] tabular-nums">
              <span className="text-[oklch(0.65_0.18_150)] font-semibold">+{file.additions ?? 0}</span>
              {" "}
              <span className="text-[oklch(0.60_0.22_30)] font-semibold">-{file.deletions ?? 0}</span>
            </span>
          ) : null}
          {commentCount > 0 ? (
            <span className="text-[11px] text-primary font-medium bg-primary/10 px-2 py-0.5 rounded-full">
              {commentCount}
            </span>
          ) : null}
          {/* View-mode segmented control, hidden when card is collapsed.
              Unified / Split mirror GitHub's "Unified" / "Split" diff toggle;
              Full file renders the whole post-change file with added-line
              highlights (GitHub's "Display the source diff" toggle). */}
          {!collapsed ? (
            <div className="inline-flex border border-border rounded-md overflow-hidden text-[11px]">
              {(["changes", "split", "full"] as const).map((m, idx) => {
                const disabled = m === "full" && !hasNewContent
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => !disabled && setMode(m)}
                    disabled={disabled}
                    title={disabled ? "Full view unavailable for this file" : MODE_LABEL[m]}
                    className={cn(
                      "px-2 py-0.5 transition-colors",
                      idx > 0 && "border-l border-border",
                      disabled
                        ? "text-muted-foreground/40 cursor-not-allowed"
                        : "cursor-pointer",
                      mode === m && !disabled
                        ? "bg-accent text-foreground font-semibold"
                        : !disabled && "text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {MODE_LABEL[m]}
                  </button>
                )
              })}
            </div>
          ) : null}
        </div>
      </div>
      {collapsed ? null : mode === "full" ? (
        <FullFileView file={file} overlay={overlay} />
      ) : (
        <DiffView file={file} mode={mode} overlay={overlay} />
      )}
    </div>
  )
}
