import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

export type StatusKind =
  | "running"
  | "completed"
  | "stopped"
  | "errored"
  | "attention"
  | "draft"

interface Props {
  kind: StatusKind
  label?: ReactNode      // overrides default label (e.g. "debug · awaiting review")
  pulse?: boolean        // defaults to true for "running"
  size?: "sm" | "md"
  className?: string
}

const STYLES: Record<StatusKind, { pill: string; dot: string; default: string }> = {
  running: {
    pill: "text-[#58a6ff] border-[#1f6feb55] bg-[#1f6feb14]",
    dot: "bg-[#58a6ff]",
    default: "running",
  },
  completed: {
    pill: "text-[#3fb950] border-[#3fb95055] bg-[#3fb95014]",
    dot: "bg-[#3fb950]",
    default: "completed",
  },
  attention: {
    pill: "text-[#d29922] border-[#d2992255] bg-[#d2992214]",
    dot: "bg-[#d29922]",
    default: "attention",
  },
  stopped: {
    pill: "text-[#8d96a0] border-[#30363d] bg-[#161b22]",
    dot: "bg-[#8d96a0]",
    default: "stopped",
  },
  errored: {
    pill: "text-[#f85149] border-[#f8514955] bg-[#f8514914]",
    dot: "bg-[#f85149]",
    default: "errored",
  },
  draft: {
    pill: "text-[#8d96a0] border-[#30363d] bg-transparent",
    dot: "bg-[#8d96a0]",
    default: "draft",
  },
}

export function StatusPill({ kind, label, pulse, size = "md", className }: Props) {
  const s = STYLES[kind]
  const showPulse = pulse ?? kind === "running"
  const showDot = kind !== "draft"
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border font-medium leading-[18px]",
        size === "sm" ? "px-2 py-px text-[11px]" : "px-2.5 py-0.5 text-[11px]",
        s.pill,
        className,
      )}
    >
      {showDot && (
        <span
          className={cn(
            "size-1.5 rounded-full shrink-0",
            s.dot,
            showPulse && "animate-orca-pulse",
          )}
        />
      )}
      <span className="truncate">{label ?? s.default}</span>
    </span>
  )
}
