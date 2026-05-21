import { cn } from "@/lib/utils"
import type { ChangesetFile } from "@/lib/schema"

const STATUS_DOT: Record<ChangesetFile["status"], string> = {
  added: "bg-[oklch(0.65_0.18_150)]",
  modified: "bg-[oklch(0.55_0.20_260)]",
  deleted: "bg-[oklch(0.60_0.22_30)]",
  renamed: "bg-muted-foreground",
}

export function FileTreeSidebar({
  files,
  commentCountFor,
  onSelectFile,
  activePath,
}: {
  files: ChangesetFile[]
  commentCountFor: (path: string) => number
  onSelectFile: (path: string) => void
  activePath?: string
}) {
  return (
    <aside className="sticky top-4 w-[280px] shrink-0 h-[calc(100vh-2rem)] overflow-y-auto pr-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground px-2 pb-2 font-semibold">
        Files
      </div>
      <ul className="space-y-0.5">
        {files.map((f) => {
          const segments = f.path.split("/")
          const filename = segments.at(-1) ?? f.path
          const dir = segments.slice(0, -1).join("/")
          const count = commentCountFor(f.path)
          const active = activePath === f.path
          return (
            <li key={f.path}>
              <button
                type="button"
                onClick={() => onSelectFile(f.path)}
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
                <span className="font-mono text-[10px] text-muted-foreground shrink-0">
                  <span className="text-[oklch(0.55_0.18_150)]">+{f.additions}</span>{" "}
                  <span className="text-[oklch(0.55_0.20_30)]">−{f.deletions}</span>
                </span>
                {count > 0 ? (
                  <span className="ml-1 rounded-full bg-primary/10 text-primary px-1.5 py-0.5 text-[10px] font-medium shrink-0">
                    {count}
                  </span>
                ) : null}
              </button>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
