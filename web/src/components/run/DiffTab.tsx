import { useCallback, useEffect, useMemo, useState } from "react"
import { ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown, GitCompareArrows } from "lucide-react"

import { cn } from "@/lib/utils"
import { DiffView, type DiffViewOverlay } from "@/components/review/DiffView"
import { FullFileView } from "@/components/review/FullFileView"
import type { ChangesetFile, FileStatus, ViewMode } from "@/components/review/types"

interface DiffFile {
  path: string
  status: string
  diff?: string
  language?: string
  old_path?: string
  additions?: number
  deletions?: number
  old_content?: string
  new_content?: string
}

interface Snapshot {
  diff_files: DiffFile[]
  base_commit: string
}

interface Attempt {
  attempt: number
  state: string
  state_local_index: number
  decision: string | null
}

interface Props {
  runId: string
  issueId: string | null
  debugPending?: boolean
  selectedState?: string | null
  selectedStateLocalIndex?: number | null
}

const STATUS_DOT: Record<FileStatus, string> = {
  added: "bg-[oklch(0.65_0.18_150)]",
  modified: "bg-[oklch(0.55_0.20_260)]",
  deleted: "bg-[oklch(0.60_0.22_30)]",
  renamed: "bg-muted-foreground",
}

const noOpOverlay: DiffViewOverlay = {
  commentsForLine: () => [],
  draftForLine: () => undefined,
  globalIndexOf: () => -1,
  onOpenDraft: () => {},
  onUpdateDraft: () => {},
  onSaveDraft: () => {},
  onCloseDraft: () => {},
  onEditComment: () => {},
  onDeleteComment: () => {},
  highlightedCommentIndex: null,
  threadFor: () => undefined,
  onReply: async () => {},
  readOnly: true,
}

function toChangesetFile(f: DiffFile): ChangesetFile {
  const known = new Set<FileStatus>(["added", "modified", "deleted", "renamed"])
  const status: FileStatus = known.has(f.status as FileStatus) ? (f.status as FileStatus) : "modified"
  return {
    path: f.path,
    status,
    old_path: f.old_path,
    language: f.language,
    additions: f.additions ?? 0,
    deletions: f.deletions ?? 0,
    diff: f.diff ?? "",
    old_content: f.old_content,
    new_content: f.new_content,
  }
}

function FileCard({ file, collapsed, onToggle }: { file: ChangesetFile; collapsed: boolean; onToggle: () => void }) {
  const [mode, setMode] = useState<ViewMode>("changes")
  const hasNewContent = typeof file.new_content === "string" && file.new_content.length > 0

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--border)] bg-[var(--subtle)]">
        <button
          type="button"
          onClick={onToggle}
          className="text-[var(--fg-muted)] hover:text-[var(--fg)] cursor-pointer shrink-0"
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        </button>
        <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", STATUS_DOT[file.status])} />
        <span className="font-mono text-[12px] font-medium truncate text-[var(--fg)]" title={file.path}>
          {file.path}
        </span>
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {(file.additions || file.deletions) ? (
            <span className="font-mono text-[11px] tabular-nums">
              <span className="text-[var(--success-fg)] font-semibold">+{file.additions}</span>{" "}
              <span className="text-[var(--danger)] font-semibold">-{file.deletions}</span>
            </span>
          ) : null}
          {!collapsed && (
            <div className="inline-flex border border-[var(--border)] rounded-md overflow-hidden text-[11px]">
              {(["changes", "split", "full"] as const).map((m, idx) => {
                const disabled = m === "full" && !hasNewContent
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => !disabled && setMode(m)}
                    disabled={disabled}
                    className={cn(
                      "px-2 py-0.5 transition-colors",
                      idx > 0 && "border-l border-[var(--border)]",
                      disabled ? "text-[var(--fg-subtle)] cursor-not-allowed" : "cursor-pointer",
                      mode === m && !disabled
                        ? "bg-[var(--accent-soft)] text-[var(--fg)] font-semibold"
                        : !disabled && "text-[var(--fg-muted)] hover:bg-[var(--subtle)]",
                    )}
                  >
                    {m === "changes" ? "Unified" : m === "split" ? "Split" : "Full"}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
      {!collapsed && (mode === "full" ? (
        <FullFileView file={file} overlay={noOpOverlay} />
      ) : (
        <DiffView file={file} mode={mode} overlay={noOpOverlay} />
      ))}
    </div>
  )
}

export function DiffTab({
  runId,
  issueId,
  debugPending,
  selectedState,
  selectedStateLocalIndex,
}: Props) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [attempts, setAttempts] = useState<Attempt[]>([])
  const [selectedAttempt, setSelectedAttempt] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [collapsedFiles, setCollapsedFiles] = useState<Set<string>>(new Set())

  // Reset state when issue/phase changes.
  useEffect(() => {
    setSnapshot(null)
    setAttempts([])
    setSelectedAttempt(null)
    setError(null)
  }, [issueId, selectedState, selectedStateLocalIndex])

  // Load attempts list and auto-select the latest
  useEffect(() => {
    if (!issueId) return
    const decoded = decodeURIComponent(runId)
    let cancelled = false

    void (async () => {
      setLoading(true)
      try {
        // If debug_pending, fetch the live snapshot directly
        if (debugPending) {
          const res = await fetch(`/api/runs/${decoded}/issues/${issueId}/debug`)
          if (!cancelled && res.ok) {
            setSnapshot(await res.json())
            setError(null)
          } else if (!cancelled) {
            setError("Debug review not available.")
          }
          return
        }

        // Otherwise, fetch the attempts list and load the latest
        const attRes = await fetch(`/api/runs/${decoded}/issues/${issueId}/debug/attempts`)
        if (cancelled) return
        if (!attRes.ok) {
          setError("No diff available for this issue yet.")
          return
        }
        const list: Attempt[] = await attRes.json()
        if (cancelled) return
        setAttempts(list)

        if (list.length === 0) {
          setError("No diff available for this issue yet.")
          return
        }

        let attempt = list[list.length - 1].attempt
        if (selectedState) {
          if (!selectedStateLocalIndex) {
            setError("No diff snapshot for this phase.")
            return
          }
          const matchingAttempt = list.find(
            (item) => item.state === selectedState && item.state_local_index === selectedStateLocalIndex,
          )
          if (!matchingAttempt) {
            setError("No diff snapshot for this phase.")
            return
          }
          attempt = matchingAttempt.attempt
        }
        setSelectedAttempt(attempt)

        const snapRes = await fetch(`/api/runs/${decoded}/issues/${issueId}/debug?attempt=${attempt}`)
        if (cancelled) return
        if (snapRes.ok) {
          setSnapshot(await snapRes.json())
          setError(null)
        } else {
          setError("Diff snapshot not found.")
        }
      } catch (exc) {
        if (!cancelled) setError(String(exc))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [issueId, runId, debugPending, selectedState, selectedStateLocalIndex])

  // Fetch snapshot when user picks a different attempt from the dropdown
  const loadAttempt = useCallback(async (attempt: number) => {
    if (!issueId) return
    const decoded = decodeURIComponent(runId)
    setSelectedAttempt(attempt)
    setLoading(true)
    try {
      const res = await fetch(`/api/runs/${decoded}/issues/${issueId}/debug?attempt=${attempt}`)
      if (res.ok) {
        setSnapshot(await res.json())
        setError(null)
      } else {
        setError("Diff snapshot not found for this attempt.")
        setSnapshot(null)
      }
    } catch (exc) {
      setError(String(exc))
    } finally {
      setLoading(false)
    }
  }, [issueId, runId])

  const files = useMemo(
    () => (snapshot?.diff_files ?? []).map(toChangesetFile),
    [snapshot],
  )

  const totalAdditions = files.reduce((s, f) => s + f.additions, 0)
  const totalDeletions = files.reduce((s, f) => s + f.deletions, 0)

  const allCollapsed = files.length > 0 && files.every((f) => collapsedFiles.has(f.path))
  const toggleAll = useCallback(() => {
    if (allCollapsed) {
      setCollapsedFiles(new Set())
    } else {
      setCollapsedFiles(new Set(files.map((f) => f.path)))
    }
  }, [allCollapsed, files])

  if (!issueId) {
    return (
      <div className="px-6 py-8 text-center text-[13px] text-[var(--fg-muted)] italic">
        Select an issue from the left.
      </div>
    )
  }

  if (loading && !snapshot) {
    return (
      <div className="px-6 py-8 text-center text-[13px] text-[var(--fg-muted)] italic">
        Loading diff…
      </div>
    )
  }

  if (error && !snapshot) {
    return (
      <div className="px-6 py-8 text-center text-[13px] text-[var(--fg-muted)]">
        <GitCompareArrows size={24} className="mx-auto mb-2 text-[var(--fg-subtle)]" />
        <p>{error}</p>
        {!debugPending && (
          <p className="mt-1 text-[11px] text-[var(--fg-subtle)]">
            Diffs become available after a worker completes a phase.
          </p>
        )}
      </div>
    )
  }

  if (!snapshot || files.length === 0) {
    return (
      <div className="px-6 py-8 text-center text-[13px] text-[var(--fg-muted)]">
        <GitCompareArrows size={24} className="mx-auto mb-2 text-[var(--fg-subtle)]" />
        <p>No file changes in this phase.</p>
      </div>
    )
  }

  return (
    <div className="px-6 py-5 max-w-[1100px] space-y-3">
      {/* Header bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-[12px] text-[var(--fg-muted)]">
          <span>
            <span className="font-semibold text-[var(--fg)]">{files.length}</span>{" "}
            {files.length === 1 ? "file" : "files"} changed
          </span>
          <span className="font-mono tabular-nums">
            <span className="text-[var(--success-fg)] font-semibold">+{totalAdditions}</span>{" "}
            <span className="text-[var(--danger)] font-semibold">-{totalDeletions}</span>
          </span>
          {snapshot.base_commit && (
            <span className="text-[var(--fg-subtle)] font-mono text-[11px]">
              base {snapshot.base_commit.slice(0, 8)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {attempts.length > 1 && (
            <select
              value={selectedAttempt ?? ""}
              onChange={(e) => void loadAttempt(Number(e.target.value))}
              className="text-[11px] bg-[var(--subtle)] border border-[var(--border)] rounded-md px-2 py-1 text-[var(--fg)]"
            >
              {attempts.map((a) => (
                <option key={a.attempt} value={a.attempt}>
                  {a.state} (v{a.state_local_index})
                  {a.decision ? ` · ${a.decision}` : ""}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={toggleAll}
            className="inline-flex items-center gap-1 text-[11px] text-[var(--fg-muted)] hover:text-[var(--fg)] cursor-pointer transition-colors"
          >
            {allCollapsed ? <ChevronsUpDown size={13} /> : <ChevronsDownUp size={13} />}
            {allCollapsed ? "Expand all" : "Collapse all"}
          </button>
        </div>
      </div>

      {/* File list */}
      {files.map((file) => (
        <FileCard
          key={file.path}
          file={file}
          collapsed={collapsedFiles.has(file.path)}
          onToggle={() =>
            setCollapsedFiles((prev) => {
              const next = new Set(prev)
              if (next.has(file.path)) next.delete(file.path)
              else next.add(file.path)
              return next
            })
          }
        />
      ))}
    </div>
  )
}
