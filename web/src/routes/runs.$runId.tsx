import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useMemo, useState } from "react"
import {
  useRunState,
  type IssueState,
  type SessionState,
} from "@/hooks/useRunState"
import { useWorkerLog } from "@/hooks/useWorkerLog"
import { formatDuration } from "@/lib/duration"
import { IssuesTree } from "@/components/run/IssuesTree"
import { PhasesPanel } from "@/components/run/PhasesPanel"
import { IssueDetailTab } from "@/components/run/IssueDetailTab"
import { WorkerLogTab } from "@/components/run/WorkerLogTab"
import { RunResultTab } from "@/components/run/RunResultTab"
import { RunHeader } from "@/components/run/RunHeader"
import { cn } from "@/lib/utils"

type Tab = "detail" | "session" | "result"

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

  const selectedIssueId = search.issue ?? null
  const selectedSessionId = search.session ?? null
  const activeTab: Tab = search.tab ?? "detail"

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
      search: { issue: running ?? ids[0], tab: "detail" } as SearchParams,
      replace: true,
    })
  }, [data, selectedIssueId, navigate, runId])

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
      search: { issue: id, tab: "detail" } as SearchParams,
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
      <main className="min-h-screen bg-background text-foreground flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-lg font-semibold mb-2">Cannot reach daemon</h1>
          <p className="text-sm text-muted-foreground">{error}</p>
        </div>
      </main>
    )
  }

  if (data === null) {
    return (
      <main className="min-h-screen bg-background text-foreground flex items-center justify-center">
        <p className="text-sm text-muted-foreground italic">Loading…</p>
      </main>
    )
  }

  return (
    <main className="h-screen flex flex-col bg-background text-foreground">
      <RunHeader
        runId={runId}
        status={data.status}
        debugMode={debugMode}
        elapsed={elapsed}
        selectedIssueId={selectedIssueId}
        selectedIssue={selectedIssue}
        onChange={() => void refetch()}
      />
      {error && data !== null && (
        <div className="px-5 py-1 text-[11px] text-amber-500 bg-amber-500/5">
          reconnecting… ({error})
        </div>
      )}
      <div className="flex-1 min-h-0 grid grid-cols-[260px_1fr]">
        {/* Left rail */}
        <aside className="border-r border-border bg-background overflow-y-auto p-3 flex flex-col gap-4">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2 px-1">
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
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2 px-1">
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

        {/* Right area */}
        <section className="flex flex-col min-h-0">
          <nav className="border-b border-border px-5 flex items-center gap-1">
            {(["detail", "session", "result"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "px-3 py-2 text-[12px] capitalize border-b-2 -mb-[2px] transition-colors",
                  activeTab === t
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {t}
              </button>
            ))}
          </nav>
          <div className="flex-1 min-h-0 overflow-y-auto">
            {activeTab === "detail" && (
              <IssueDetailTab runId={runId} issueId={selectedIssueId} issue={selectedIssue} />
            )}
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
            {activeTab === "result" && (
              <RunResultTab
                result={resultData as Record<string, unknown> | null}
                activeSession={selectedSession?.completed_at === null}
              />
            )}
          </div>
        </section>
      </div>
    </main>
  )
}

export const Route = createFileRoute("/runs/$runId")({
  component: RunViewerPage,
  validateSearch: (raw: Record<string, unknown>): SearchParams => ({
    issue: typeof raw.issue === "string" ? raw.issue : undefined,
    session: typeof raw.session === "string" ? raw.session : undefined,
    tab:
      raw.tab === "detail" || raw.tab === "session" || raw.tab === "result"
        ? raw.tab
        : undefined,
  }),
})
