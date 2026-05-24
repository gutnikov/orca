import { useMemo, useState } from "react"
import { Search } from "lucide-react"

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
  const [filter, setFilter] = useState("")
  const q = filter.trim().toLowerCase()

  const matchesQ = (s: string) => !q || s.toLowerCase().includes(q)

  const filteredVirtual = useMemo(
    () => virtualFiles.filter((f) => matchesQ(f.label) || matchesQ(f.id)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [virtualFiles, q],
  )
  const filteredReal = useMemo(
    () => realFiles.filter((f) => matchesQ(f.path)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [realFiles, q],
  )

  return (
    <aside className="w-full h-full flex flex-col gap-3 overflow-hidden">
      {/* Filter input */}
      <div className="relative shrink-0">
        <Search
          size={13}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/70"
        />
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter files…"
          className={cn(
            "w-full h-8 pl-8 pr-2 text-[13px]",
            "bg-background border border-border rounded-md",
            "placeholder:text-muted-foreground/70",
            "outline-none focus:border-primary/50 focus-visible:ring-0 transition-colors",
          )}
        />
      </div>

      <div className="flex-1 overflow-y-auto pr-1 space-y-3">
        {/* Virtual review surfaces */}
        {filteredVirtual.length > 0 ? (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground/80 px-2 pb-1.5 font-semibold">
              Review surfaces
            </div>
            <ul className="space-y-0.5">
              {filteredVirtual.map((f) => {
                const active = selectedId === f.id
                return (
                  <li key={f.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(f.id)}
                      className={cn(
                        "w-full text-left rounded-md px-2 py-1.5 flex items-center gap-2 cursor-pointer",
                        "transition-colors",
                        active
                          ? "bg-primary/10 text-foreground"
                          : "hover:bg-muted/60 text-foreground/85",
                      )}
                    >
                      <span
                        className={cn(
                          "h-1.5 w-1.5 rounded-full shrink-0",
                          active ? "bg-primary" : "bg-primary/40",
                        )}
                      />
                      <span className="font-mono text-[12px] truncate min-w-0 flex-1 font-semibold">
                        {f.label}
                      </span>
                      {f.commentCount > 0 ? (
                        <span className="ml-1 rounded-full bg-primary/15 text-primary px-1.5 py-0.5 text-[10px] font-semibold shrink-0 tabular-nums">
                          {f.commentCount}
                        </span>
                      ) : null}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ) : null}

        {/* Real changeset files */}
        {filteredReal.length > 0 ? (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground/80 px-2 pb-1.5 font-semibold flex items-center justify-between">
              <span>Changes</span>
              <span className="text-muted-foreground/60 tabular-nums">
                {filteredReal.length}
              </span>
            </div>
            <ul className="space-y-0.5">
              {filteredReal.map((f) => {
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
                        "w-full text-left rounded-md px-2 py-1.5 flex items-center gap-2 cursor-pointer",
                        "transition-colors",
                        active
                          ? "bg-primary/10 text-foreground"
                          : "hover:bg-muted/60 text-foreground/85",
                      )}
                      title={f.path}
                    >
                      <span
                        className={cn("h-1.5 w-1.5 rounded-full shrink-0", STATUS_DOT[f.status])}
                      />
                      <span className="font-mono text-[12px] truncate min-w-0 flex-1">
                        {dir ? <span className="text-muted-foreground/70">{dir}/</span> : null}
                        <span className="font-semibold">{filename}</span>
                      </span>
                      {f.commentCount > 0 ? (
                        <span className="ml-1 rounded-full bg-primary/15 text-primary px-1.5 py-0.5 text-[10px] font-semibold shrink-0 tabular-nums">
                          {f.commentCount}
                        </span>
                      ) : null}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ) : null}

        {filteredVirtual.length === 0 && filteredReal.length === 0 ? (
          <div className="px-2 py-4 text-[12px] text-muted-foreground/70 italic">
            No files match “{filter}”
          </div>
        ) : null}
      </div>
    </aside>
  )
}
