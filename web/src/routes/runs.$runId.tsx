import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useState } from "react"
import type { PointerEvent as ReactPointerEvent } from "react"
import { toast } from "sonner"
import { ChevronDown, ChevronRight } from "lucide-react"
import {
  useRunState,
  type IssueState,
  type SessionState,
} from "@/hooks/useRunState"
import { useWorkerLog } from "@/hooks/useWorkerLog"
import { formatDuration } from "@/lib/duration"
import { cn } from "@/lib/utils"
import { IssuesTree } from "@/components/run/IssuesTree"
import { PhasesPanel } from "@/components/run/PhasesPanel"
import { IssueDetailTab } from "@/components/run/IssueDetailTab"
import { WorkerLogTab } from "@/components/run/WorkerLogTab"
import { RunResultTab } from "@/components/run/RunResultTab"
import { DiffTab } from "@/components/run/DiffTab"
import { RunHeader } from "@/components/run/RunHeader"
import { AppShell, AppHeader } from "@/components/ui/app-shell"

type Tab = "session" | "result" | "diff"

const SIDEBAR_STORAGE_KEY = "orca.runSidebarWidth"
const SIDEBAR_DEFAULT_WIDTH = 340
const SIDEBAR_MIN_WIDTH = 260
const SIDEBAR_MAX_WIDTH = 560

function clampSidebarWidth(value: number): number {
  const viewportMax =
    typeof window === "undefined"
      ? SIDEBAR_MAX_WIDTH
      : Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, window.innerWidth - 420))
  return Math.min(Math.max(value, SIDEBAR_MIN_WIDTH), viewportMax)
}

function initialSidebarWidth(): number {
  if (typeof window === "undefined") return SIDEBAR_DEFAULT_WIDTH
  const stored = Number(window.localStorage.getItem(SIDEBAR_STORAGE_KEY))
  return clampSidebarWidth(Number.isFinite(stored) && stored > 0 ? stored : SIDEBAR_DEFAULT_WIDTH)
}

interface SearchParams {
  issue?: string
  session?: string
  tab?: Tab
}

function RunViewerPage() {
  const { runId } = Route.useParams()
  const search = Route.useSearch() as SearchParams
  const navigate = useNavigate()

  const { data, error, refetch } = useRunState(runId)
  const [tail, setTail] = useState(500)
  const [detailOpen, setDetailOpen] = useState(false)
  const [sidebarWidth, setSidebarWidth] = useState(initialSidebarWidth)

  const selectedIssueId = search.issue ?? null
  const selectedSessionId = search.session ?? null
  const activeTab: Tab = (search.tab as Tab) ?? "session"

  // Build outcomes map by pairing completed sessions with worker_result events
  // (mirrors tui/app.py:_session_result_map — zip-by-order matching).
  const outcomes: Record<string, string> = useMemo(() => {
    if (!data) return {}
    const out: Record<string, string> = {}
    for (const [iid, issue] of Object.entries(data.state.issues)) {
      const completed = data.sessions
        .filter((s) => s.issue_id === iid && s.completed_at !== null)
        .sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at))
      const log = issue.event_log
      if (!Array.isArray(log)) continue
      const resultEvents = log.filter((e) => e.type === "worker_result")
      for (let i = 0; i < completed.length && i < resultEvents.length; i++) {
        const sid = completed[i].session_id
        const outcome = resultEvents[i].data.outcome
        if (typeof outcome === "string") out[sid] = outcome
      }
    }
    return out
  }, [data])

  // Default issue selection: first running issue, else first issue.
  useEffect(() => {
    if (!data) return
    if (selectedIssueId && data.state.issues[selectedIssueId]) return
    const ids = Object.keys(data.state.issues)
    if (ids.length === 0) return
    const running = ids.find((id) => data.state.issues[id].worker_active)
    void navigate({
      to: "/runs/$runId",
      params: { runId },
      search: { issue: running ?? ids[0], tab: "session" } as SearchParams,
      replace: true,
    })
  }, [data, selectedIssueId, navigate, runId])

  // Surface daemon-reconnect state as an unobtrusive toast.
  useEffect(() => {
    if (!error || data === null) return
    const id = toast("Reconnecting to daemon…", {
      duration: 4000,
      description: error,
    })
    return () => {
      toast.dismiss(id)
    }
  }, [error, data])

  const selectedIssue: IssueState | null =
    selectedIssueId && data ? (data.state.issues[selectedIssueId] ?? null) : null

  const selectedSession: SessionState | null = useMemo(
    () =>
      data && selectedSessionId
        ? (data.sessions.find((s) => s.session_id === selectedSessionId) ?? null)
        : null,
    [data, selectedSessionId],
  )

  const debugMode = useMemo(
    () =>
      data
        ? Object.values(data.state.issues).some((i) => i.debug_pending)
        : false,
    [data],
  )

  const issueCount = data ? Object.keys(data.state.issues).length : 0
  const doneCount = data
    ? Object.values(data.state.issues).filter((i) => i.state === "done").length
    : 0

  const elapsed = useMemo(() => {
    if (!data) return ""
    const starts = data.sessions
      .map((s) => Date.parse(s.started_at))
      .filter((n) => !Number.isNaN(n))
    if (starts.length === 0) return ""
    const earliest = new Date(Math.min(...starts)).toISOString()
    return formatDuration(earliest, data.status === "completed" ? new Date().toISOString() : null)
  }, [data])

  const selectIssue = (id: string) => {
    void navigate({
      to: "/runs/$runId",
      params: { runId },
      search: { issue: id, tab: activeTab } as SearchParams,
      replace: true,
    })
  }

  const selectSession = (sid: string) => {
    if (!selectedIssueId) return
    void navigate({
      to: "/runs/$runId",
      params: { runId },
      search: { issue: selectedIssueId, session: sid, tab: "session" } as SearchParams,
      replace: true,
    })
    // Boost log capture frequency for the focused session.
    void fetch(`/api/runs/${runId}/hot-session`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: sid, hot: true }),
    })
  }

  const setTab = (t: Tab) => {
    void navigate({
      to: "/runs/$runId",
      params: { runId },
      search: {
        issue: selectedIssueId ?? undefined,
        session: selectedSessionId ?? undefined,
        tab: t,
      } as SearchParams,
      replace: true,
    })
  }

  const startSidebarResize = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = sidebarWidth
    let latestWidth = startWidth
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"

    const onMove = (moveEvent: PointerEvent) => {
      latestWidth = clampSidebarWidth(startWidth + moveEvent.clientX - startX)
      setSidebarWidth(latestWidth)
    }
    const onUp = () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(latestWidth))
    }

    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
  }, [sidebarWidth])

  const resizeSidebarBy = useCallback((delta: number) => {
    setSidebarWidth((current) => {
      const next = clampSidebarWidth(current + delta)
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next))
      return next
    })
  }, [])

  const logIssueId = selectedSession ? selectedSession.issue_id : selectedIssueId
  const { text: logText, error: logError } = useWorkerLog(
    runId,
    logIssueId,
    selectedSessionId,
    tail,
  )

  // Result data — read from the session's matching worker_result event.
  const resultData = useMemo(() => {
    if (!selectedSession || !data) return null
    const issue = data.state.issues[selectedSession.issue_id]
    const log = issue?.event_log
    if (!Array.isArray(log)) return null
    const completed = data.sessions
      .filter((s) => s.issue_id === selectedSession.issue_id && s.completed_at !== null)
      .sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at))
    const results = log.filter((e) => e.type === "worker_result")
    const idx = completed.findIndex((s) => s.session_id === selectedSession.session_id)
    if (idx === -1 || idx >= results.length) return null
    return results[idx].data
  }, [selectedSession, data])

  if (error && data === null) {
    return (
      <AppShell className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <h1 className="text-[16px] font-semibold mb-2">Cannot reach daemon</h1>
          <p className="text-[13px] text-[var(--fg-muted)]">{error}</p>
        </div>
      </AppShell>
    )
  }

  if (data === null) {
    return (
      <AppShell className="flex items-center justify-center min-h-screen">
        <p className="text-[13px] text-[var(--fg-muted)] italic">Loading…</p>
      </AppShell>
    )
  }

  return (
    <AppShell className="flex flex-col h-screen">
      <AppHeader
        breadcrumb={[
          { label: "orca", to: "/" },
          { label: "runs", to: "/" },
          { label: runId, mono: true },
        ]}
      />
      <RunHeader
        runId={runId}
        status={data.status}
        debugMode={debugMode}
        elapsed={elapsed}
        issueCount={issueCount}
        doneCount={doneCount}
        selectedIssueId={selectedIssueId}
        selectedIssue={selectedIssue}
        onChange={() => void refetch()}
      />
      <div
        className="flex-1 min-h-0 grid"
        style={{ gridTemplateColumns: `${sidebarWidth}px 6px minmax(0,1fr)` }}
      >
        <aside className="bg-[var(--canvas)] overflow-y-auto p-3 flex flex-col gap-4 min-w-0">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[var(--fg-subtle)] mb-2 px-1 font-semibold">
              Issues
            </div>
            <IssuesTree
              issues={data.state.issues}
              selectedIssueId={selectedIssueId}
              onSelect={selectIssue}
            />
          </div>
          {selectedIssueId && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[var(--fg-subtle)] mb-2 px-1 font-semibold">
                Phases
              </div>
              <PhasesPanel
                sessions={data.sessions}
                issueId={selectedIssueId}
                outcomes={outcomes}
                selectedSessionId={selectedSessionId}
                onSelect={selectSession}
              />
            </div>
          )}
        </aside>

        <div
          role="separator"
          aria-label="Resize sidebar"
          aria-orientation="vertical"
          aria-valuemin={SIDEBAR_MIN_WIDTH}
          aria-valuemax={SIDEBAR_MAX_WIDTH}
          aria-valuenow={sidebarWidth}
          tabIndex={0}
          onPointerDown={startSidebarResize}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") {
              event.preventDefault()
              resizeSidebarBy(-20)
            } else if (event.key === "ArrowRight") {
              event.preventDefault()
              resizeSidebarBy(20)
            }
          }}
          className="group cursor-col-resize bg-[var(--canvas)] border-x border-[var(--border)] flex justify-center touch-none outline-none focus:bg-[var(--subtle)]"
        >
          <div className="w-px h-full bg-transparent group-hover:bg-[var(--accent)] transition-colors" />
        </div>

        <section className="flex flex-col min-h-0 bg-[var(--canvas)]">
          {/* Collapsible issue detail */}
          {selectedIssueId && selectedIssue && (
            <div className="border-b border-[var(--border)]">
              <button
                type="button"
                onClick={() => setDetailOpen((v) => !v)}
                className="w-full flex items-center gap-2 px-5 py-2 text-left hover:bg-[var(--subtle)] transition-colors"
              >
                {detailOpen
                  ? <ChevronDown size={14} className="text-[var(--fg-subtle)] shrink-0" />
                  : <ChevronRight size={14} className="text-[var(--fg-subtle)] shrink-0" />
                }
                <span className="text-[12px] font-semibold text-[var(--fg-muted)] uppercase tracking-wider">
                  Issue
                </span>
                <span className="text-[12px] text-[var(--fg)] truncate">
                  {selectedIssue.fields?.title || selectedIssueId}
                </span>
              </button>
              {detailOpen && (
                <IssueDetailTab runId={runId} issueId={selectedIssueId} issue={selectedIssue} />
              )}
            </div>
          )}

          {/* Per-phase tab bar */}
          <div className="border-b border-[var(--border)] px-5 flex items-center gap-1">
            {(["session", "diff", "result"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "px-3 py-2 text-[13px] capitalize border-b-2 -mb-px transition-colors",
                  activeTab === t
                    ? "border-[var(--accent-warm)] text-[var(--fg)] font-medium"
                    : "border-transparent text-[var(--fg-muted)] hover:text-[var(--fg)]",
                )}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Per-phase tab content */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            {activeTab === "session" && (
              <WorkerLogTab
                text={logText}
                error={logError}
                session={selectedSession}
                outcome={selectedSession ? outcomes[selectedSession.session_id] : undefined}
                onIncreaseTail={() => setTail(2000)}
                largeTail={tail >= 2000}
              />
            )}
            {activeTab === "diff" && (
              <DiffTab
                runId={runId}
                issueId={selectedIssueId}
                debugPending={selectedIssue?.debug_pending}
              />
            )}
            {activeTab === "result" && (
              <RunResultTab
                result={resultData as Record<string, unknown> | null}
                activeSession={selectedSession?.completed_at === null}
              />
            )}
          </div>
        </section>
      </div>
    </AppShell>
  )
}

export const Route = createFileRoute("/runs/$runId")({
  component: RunViewerPage,
  validateSearch: (raw: Record<string, unknown>): SearchParams => ({
    issue: typeof raw.issue === "string" ? raw.issue : undefined,
    session: typeof raw.session === "string" ? raw.session : undefined,
    tab:
      raw.tab === "session" || raw.tab === "result" || raw.tab === "diff"
        ? raw.tab
        : undefined,
  }),
})
