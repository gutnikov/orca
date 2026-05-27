import { useMemo } from "react"
import { ChevronRight, Loader2, CheckCircle2, AlertTriangle, Pause } from "lucide-react"
import type { IssueState } from "@/hooks/useRunState"
import { cn } from "@/lib/utils"

interface Props {
  issues: Record<string, IssueState>
  selectedIssueId: string | null
  onSelect: (issueId: string) => void
}

interface TreeNode {
  issueId: string
  children: TreeNode[]
}

function buildTree(issues: Record<string, IssueState>): TreeNode[] {
  const childrenByParent: Record<string, string[]> = {}
  const roots: string[] = []
  for (const [iid, iss] of Object.entries(issues)) {
    const parent = iss.decomposed_from
    // Treat orphans (parent missing from this snapshot) as roots rather than
    // silently dropping them — defensive against partial / stale state.
    if (parent === null || !(parent in issues)) {
      roots.push(iid)
    } else {
      childrenByParent[parent] ??= []
      childrenByParent[parent].push(iid)
    }
  }
  const toNode = (iid: string): TreeNode => ({
    issueId: iid,
    children: (childrenByParent[iid] ?? []).map(toNode),
  })
  return roots.map(toNode)
}

function IssueIcon({ issue }: { issue: IssueState }) {
  if (issue.debug_pending) return <Pause size={12} className="text-[var(--attention)]" />
  if (issue.worker_active) return <Loader2 size={12} className="animate-spin text-[var(--accent-fg)]" />
  if (issue.state === "done") return <CheckCircle2 size={12} className="text-[var(--success-fg)]" />
  if (issue.failure_count > 0) return <AlertTriangle size={12} className="text-[var(--attention)]" />
  return <ChevronRight size={12} className="text-[var(--fg-subtle)]" />
}

function Row({
  node,
  depth,
  issues,
  selectedIssueId,
  onSelect,
}: {
  node: TreeNode
  depth: number
  issues: Record<string, IssueState>
  selectedIssueId: string | null
  onSelect: (id: string) => void
}) {
  const issue = issues[node.issueId]
  if (!issue) return null
  const isSelected = node.issueId === selectedIssueId
  const title = issue.fields?.title || node.issueId
  return (
    <>
      <button
        type="button"
        onClick={() => onSelect(node.issueId)}
        className={cn(
          "w-full text-left flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px]",
          "transition-colors",
          isSelected
            ? "bg-[var(--accent-soft)] border-l-2 border-[var(--accent)] text-[var(--fg)]"
            : "hover:bg-[var(--subtle)] text-[var(--fg-muted)]",
        )}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <IssueIcon issue={issue} />
        <span className="truncate flex-1">{title}</span>
        {issue.failure_count > 0 && (
          <span className="text-[10px] text-[var(--attention)] font-mono">×{issue.failure_count}</span>
        )}
      </button>
      {node.children.map((child) => (
        <Row
          key={child.issueId}
          node={child}
          depth={depth + 1}
          issues={issues}
          selectedIssueId={selectedIssueId}
          onSelect={onSelect}
        />
      ))}
    </>
  )
}

export function IssuesTree({ issues, selectedIssueId, onSelect }: Props) {
  const tree = useMemo(() => buildTree(issues), [issues])
  if (tree.length === 0) {
    return <div className="px-2 py-1 text-[12px] text-muted-foreground italic">No issues yet.</div>
  }
  return (
    <div className="flex flex-col gap-0.5">
      {tree.map((root) => (
        <Row
          key={root.issueId}
          node={root}
          depth={0}
          issues={issues}
          selectedIssueId={selectedIssueId}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}
