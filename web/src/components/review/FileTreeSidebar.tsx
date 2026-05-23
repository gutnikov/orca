import { cn } from "@/lib/utils"
import type { FileStatus } from "./types"

const STATUS_DOT: Record<FileStatus, string> = {
  added: "bg-[oklch(0.65_0.18_150)]",
  modified: "bg-[oklch(0.55_0.20_260)]",
  deleted: "bg-[oklch(0.60_0.22_30)]",
  renamed: "bg-muted-foreground",
}

export interface VirtualFileEntry {
  id: string
  label: string
  commentCount: number
}

export interface RealFileEntry {
  path: string
  status: FileStatus
  commentCount: number
}

export function FileTreeSidebar({
  virtualFiles,
  realFiles,
  selectedId,
  onSelect,
}: {
  virtualFiles: VirtualFileEntry[]
  realFiles: RealFileEntry[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  return (
    <aside className="sticky top-4 w-[280px] shrink-0 h-[calc(100vh-2rem)] overflow-y-auto pr-2">
      {/* Virtual review surfaces: prompt, result, flow state */}
      {virtualFiles.length > 0 ? (
        <>
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground px-2 pb-2 font-semibold">
            Review surfaces
          </div>
          <ul className="space-y-0.5">
            {virtualFiles.map((f) => {
              const active = selectedId === f.id
              return (
                <li key={f.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(f.id)}
                    className={cn(
                      "w-full text-left rounded-md px-2 py-1.5 flex items-center gap-2",
                      "hover:bg-muted/60 transition-colors",
                      active && "bg-muted",
                    )}
                  >
                    <span className="h-1.5 w-1.5 rounded-full shrink-0 bg-primary/40" />
                    <span className="font-mono text-xs truncate min-w-0 flex-1 font-semibold">
                      {f.label}
                    </span>
                    {f.commentCount > 0 ? (
                      <span className="ml-1 rounded-full bg-primary/10 text-primary px-1.5 py-0.5 text-[10px] font-medium shrink-0">
                        {f.commentCount}
                      </span>
                    ) : null}
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      ) : null}

      {/* Divider between virtual and real files */}
      {virtualFiles.length > 0 && realFiles.length > 0 ? (
        <div className="my-2 border-t border-border/60" />
      ) : null}

      {/* Real changeset files */}
      {realFiles.length > 0 ? (
        <>
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground px-2 pb-2 font-semibold">
            Changes ({realFiles.length} {realFiles.length === 1 ? "file" : "files"})
          </div>
          <ul className="space-y-0.5">
            {realFiles.map((f) => {
              const segments = f.path.split("/")
              const filename = segments.at(-1) ?? f.path
              const dir = segments.slice(0, -1).join("/")
              const active = selectedId === f.path
              return (
                <li key={f.path}>
                  <button
                    type="button"
                    onClick={() => onSelect(f.path)}
                    className={cn(
                      "w-full text-left rounded-md px-2 py-1.5 flex items-center gap-2",
                      "hover:bg-muted/60 transition-colors",
                      active && "bg-muted",
                    )}
                  >
                    <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", STATUS_DOT[f.status])} />
                    <span className="font-mono text-xs truncate min-w-0 flex-1">
                      {dir ? <span className="text-muted-foreground">{dir}/</span> : null}
                      <span className="font-semibold">{filename}</span>
                    </span>
                    {f.commentCount > 0 ? (
                      <span className="ml-1 rounded-full bg-primary/10 text-primary px-1.5 py-0.5 text-[10px] font-medium shrink-0">
                        {f.commentCount}
                      </span>
                    ) : null}
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      ) : null}
    </aside>
  )
}
