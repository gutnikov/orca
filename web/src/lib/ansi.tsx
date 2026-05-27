import type { ReactNode } from "react"

// 30–37 = foreground colors, 90–97 = bright variants, 0/39 = reset.
// Map to Tailwind classes that already exist in the project palette.
const FG_CLASS: Record<number, string> = {
  30: "text-foreground/70",
  31: "text-red-400",
  32: "text-emerald-400",
  33: "text-amber-400",
  34: "text-sky-400",
  35: "text-fuchsia-400",
  36: "text-cyan-400",
  37: "text-foreground",
  90: "text-muted-foreground",
  91: "text-red-300",
  92: "text-emerald-300",
  93: "text-amber-300",
  94: "text-sky-300",
  95: "text-fuchsia-300",
  96: "text-cyan-300",
  97: "text-foreground",
}

const ANSI_RE = /\x1b\[([0-9;]*)m/g

export function renderAnsi(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let currentClass: string | undefined
  let cursor = 0
  let key = 0
  // Use matchAll for safe, non-stateful iteration over global regex matches.
  const matches = Array.from(text.matchAll(ANSI_RE))
  for (const match of matches) {
    const idx = match.index ?? 0
    const before = text.slice(cursor, idx)
    if (before) {
      nodes.push(
        currentClass
          ? <span key={`s${key++}`} className={currentClass}>{before}</span>
          : <span key={`s${key++}`}>{before}</span>
      )
    }
    const codes = match[1]
      .split(";")
      .map((s) => parseInt(s, 10))
      .filter((n) => !Number.isNaN(n))
    for (const code of codes) {
      if (code === 0 || code === 39) {
        currentClass = undefined
      } else if (FG_CLASS[code]) {
        currentClass = FG_CLASS[code]
      }
    }
    cursor = idx + match[0].length
  }
  const rest = text.slice(cursor)
  if (rest) {
    nodes.push(
      currentClass
        ? <span key={`s${key++}`} className={currentClass}>{rest}</span>
        : <span key={`s${key++}`}>{rest}</span>
    )
  }
  return nodes
}
