import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * Generic, type-driven prettifier for a worker's result object.
 *
 * No assumptions about field names. Rendering decisions come only from the
 * value's JSON type and a single short-vs-long string heuristic:
 *
 *   - null                    → italic "null"
 *   - boolean / number        → inline pill
 *   - string (short, 1 line)  → inline pill next to the label
 *   - string (long / wrapped) → block paragraph with whitespace-pre-wrap
 *   - array                   → vertical list, each item recursively rendered
 *   - object                  → indented key/value list, each entry recursive
 *
 * Strings ALWAYS wrap at the right edge — that's the primary fix vs raw JSON.
 */
export function PrettyResultView({ result }: { result: Record<string, unknown> }) {
  const entries = Object.entries(result)
  if (entries.length === 0) {
    return (
      <div className="px-5 py-6 text-center text-[13px] text-muted-foreground italic">
        Worker returned an empty result.
      </div>
    )
  }
  return (
    <div className="px-5 py-4 space-y-4">
      {entries.map(([key, value]) => (
        <Field key={key} k={key} v={value} />
      ))}
    </div>
  )
}

function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1.5 font-mono">
      {children}
    </div>
  )
}

const SHORT_STRING_LIMIT = 60

function isInlineScalar(v: unknown): boolean {
  if (v === null) return true
  if (typeof v === "boolean" || typeof v === "number") return true
  if (typeof v === "string") return v.length <= SHORT_STRING_LIMIT && !v.includes("\n")
  return false
}

function Field({ k, v }: { k: string; v: unknown }) {
  if (isInlineScalar(v)) {
    return (
      <div className="flex items-baseline gap-2 flex-wrap">
        <FieldLabel>{k}</FieldLabel>
        <ScalarInline v={v} />
      </div>
    )
  }
  return (
    <div>
      <FieldLabel>{k}</FieldLabel>
      <Value v={v} />
    </div>
  )
}

function ScalarInline({ v }: { v: unknown }) {
  if (v === null) {
    return <span className="text-[13px] text-muted-foreground italic">null</span>
  }
  return (
    <code className="text-[13px] text-foreground bg-muted px-1.5 py-0.5 rounded font-mono break-all">
      {String(v)}
    </code>
  )
}

function StringBlock({ text }: { text: string }) {
  return (
    <div
      className={cn(
        "text-[13px] text-foreground/95 leading-relaxed",
        "whitespace-pre-wrap break-words font-sans",
        "bg-muted/30 border border-border/60 rounded-md px-3 py-2",
      )}
    >
      {text}
    </div>
  )
}

function Value({ v }: { v: unknown }) {
  if (v === null) {
    return <span className="text-[13px] text-muted-foreground italic">null</span>
  }
  if (typeof v === "string") {
    // Reaches here only when the string is long or multi-line (per isInlineScalar).
    return <StringBlock text={v} />
  }
  if (typeof v === "number" || typeof v === "boolean") {
    return <ScalarInline v={v} />
  }
  if (Array.isArray(v)) {
    if (v.length === 0) {
      return <span className="text-[13px] text-muted-foreground italic">empty list</span>
    }
    return (
      <ul className="space-y-1.5 pl-0 list-none">
        {v.map((it, i) => (
          <li
            key={i}
            className="flex items-baseline gap-2 min-w-0"
          >
            <span className="text-[11px] text-muted-foreground/70 font-mono tabular-nums shrink-0 mt-[2px]">
              {i + 1}.
            </span>
            <div className="flex-1 min-w-0">
              {isInlineScalar(it) ? <ScalarInline v={it} /> : <Value v={it} />}
            </div>
          </li>
        ))}
      </ul>
    )
  }
  if (typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>)
    if (entries.length === 0) {
      return <span className="text-[13px] text-muted-foreground italic">empty object</span>
    }
    return (
      <div className="space-y-3 pl-3 border-l-2 border-border/60">
        {entries.map(([k, vv]) => (
          <Field key={k} k={k} v={vv} />
        ))}
      </div>
    )
  }
  return null
}
