import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Link } from "@tanstack/react-router"
import { Pause, ChevronRight } from "lucide-react"
import type { IssueState } from "@/hooks/useRunState"

interface Props {
  runId: string
  issueId: string | null
  issue: IssueState | null
}

export function IssueDetailTab({ runId, issueId, issue }: Props) {
  if (issueId === null || issue === null) {
    return (
      <div className="px-6 py-8 text-center text-[13px] text-[var(--fg-muted)] italic">
        Select an issue from the left.
      </div>
    )
  }
  const title = issue.fields?.title || issueId
  const body = typeof issue.fields?.body === "string" ? issue.fields.body : ""
  return (
    <div className="px-6 py-5 space-y-4 max-w-[900px]">
      <header>
        <div className="text-[11px] text-[var(--fg-subtle)] font-mono mb-1">{issueId}</div>
        <h1 className="text-[20px] font-semibold tracking-tight text-[var(--fg)]">{title}</h1>
        <div className="mt-1.5 flex items-center gap-2 text-[11px] text-[var(--fg-muted)]">
          <span>state</span>
          <span className="font-mono bg-[var(--subtle)] px-1.5 py-px rounded-sm text-[var(--fg)]">
            {issue.state}
          </span>
          {issue.failure_count > 0 && (
            <span className="text-[var(--attention)] font-mono">{issue.failure_count} failures</span>
          )}
        </div>
      </header>

      {issue.debug_pending && (
        <Link
          to="/debug/$runId/$issueId"
          params={{ runId, issueId }}
          className="block rounded-md border-l-2 border-[var(--attention)] border-y border-r border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--subtle)] transition-colors px-4 py-3"
        >
          <div className="flex items-center gap-3">
            <Pause size={16} className="text-[var(--attention)]" />
            <div className="flex-1">
              <div className="text-[13px] font-semibold text-[var(--fg)]">Awaiting your review</div>
              <div className="text-[11px] text-[var(--fg-muted)] mt-0.5">
                Open the debug review to accept, modify, or stop.
              </div>
            </div>
            <ChevronRight size={16} className="text-[var(--fg-subtle)]" />
          </div>
        </Link>
      )}

      {body ? (
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
        </div>
      ) : (
        <div className="text-[13px] text-[var(--fg-muted)] italic">No body for this issue.</div>
      )}
    </div>
  )
}
