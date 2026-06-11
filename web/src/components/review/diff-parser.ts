import type { Hunk, HunkRow, DiffRow, SplitDiffRow, SplitRowPair } from "./types"

const HUNK_HEADER_RE = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/

export function parseUnifiedDiff(text: string): Hunk[] {
  const hunks: Hunk[] = []
  let current: Hunk | null = null
  let oldCursor = 0
  let newCursor = 0
  let oldRemaining = 0
  let newRemaining = 0

  const lines = text.split("\n")
  for (const line of lines) {
    const m = line.match(HUNK_HEADER_RE)
    if (m) {
      if (current) hunks.push(current)
      const oldStart = parseInt(m[1], 10)
      const oldLines = m[2] ? parseInt(m[2], 10) : 1
      const newStart = parseInt(m[3], 10)
      const newLines = m[4] ? parseInt(m[4], 10) : 1
      current = { oldStart, oldLines, newStart, newLines, header: line, rows: [] }
      oldCursor = oldStart
      newCursor = newStart
      oldRemaining = oldLines
      newRemaining = newLines
      continue
    }
    // Outside a hunk (file headers like ---/+++/diff/index, or trailer lines
    // after a hunk's declared line counts are exhausted) nothing is content.
    // Inside a hunk, a line starting with "---" is a removed line "--…" and
    // must NOT be skipped, or every old-side line number after it shifts.
    if (!current) continue
    if (oldRemaining <= 0 && newRemaining <= 0) continue
    // "\ No newline at end of file" — metadata, consumes neither cursor.
    if (line.startsWith("\\")) continue

    if (line.startsWith("+")) {
      current.rows.push({ type: "added", oldLine: null, newLine: newCursor, text: line.slice(1) })
      newCursor++
      newRemaining--
    } else if (line.startsWith("-")) {
      current.rows.push({ type: "removed", oldLine: oldCursor, newLine: null, text: line.slice(1) })
      oldCursor++
      oldRemaining--
    } else {
      const text = line.startsWith(" ") ? line.slice(1) : line
      current.rows.push({ type: "context", oldLine: oldCursor, newLine: newCursor, text })
      oldCursor++
      newCursor++
      oldRemaining--
      newRemaining--
    }
  }
  if (current) hunks.push(current)
  return hunks
}

export function hunksToUnifiedRows(hunks: Hunk[]): DiffRow[] {
  const out: DiffRow[] = []
  for (const [hi, hunk] of hunks.entries()) {
    out.push({ kind: "hunk-header", header: hunk.header, rowKey: `h-${hi}-header` })
    for (const [ri, row] of hunk.rows.entries()) {
      out.push({ kind: "row", row, rowKey: `h-${hi}-r-${ri}` })
    }
  }
  return out
}

export function hunksToSplitRows(hunks: Hunk[]): SplitDiffRow[] {
  const out: SplitDiffRow[] = []
  for (const [hi, hunk] of hunks.entries()) {
    out.push({ kind: "hunk-header", header: hunk.header, rowKey: `sh-${hi}-header` })
    let i = 0
    let pairCounter = 0
    while (i < hunk.rows.length) {
      const r = hunk.rows[i]
      if (r.type === "context") {
        out.push({ kind: "pair", pair: { rowKey: `sh-${hi}-p-${pairCounter++}`, left: r, right: r } })
        i++
        continue
      }
      const removed: HunkRow[] = []
      const added: HunkRow[] = []
      while (i < hunk.rows.length && hunk.rows[i].type === "removed") {
        removed.push(hunk.rows[i])
        i++
      }
      while (i < hunk.rows.length && hunk.rows[i].type === "added") {
        added.push(hunk.rows[i])
        i++
      }
      const max = Math.max(removed.length, added.length)
      for (let k = 0; k < max; k++) {
        const pair: SplitRowPair = {
          rowKey: `sh-${hi}-p-${pairCounter++}`,
          left: removed[k] ?? null,
          right: added[k] ?? null,
        }
        out.push({ kind: "pair", pair })
      }
    }
  }
  return out
}
