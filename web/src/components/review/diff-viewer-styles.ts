export const rowStyles = {
  // `minmax(0, 1fr)` for the content track is critical: a bare `1fr` does NOT
  // include `min-width: 0`, so long unbroken lines (markdown paragraphs, JSON
  // blobs) force the grid track to outgrow its container — the diff's
  // overflow-x-auto wrapper then sees a row WIDER than itself but renders the
  // content bleeding past the card's right edge instead of scrolling cleanly.
  base: "group/row grid grid-cols-[3rem_3rem_2rem_minmax(0,1fr)] gap-0 font-mono text-[12px] leading-5 min-h-5",
  // Solid backgrounds (no alpha) — semi-transparent row bgs let scrolled
  // content text bleed through the sticky gutter cells (which use
  // `bg-inherit`), making line numbers and +/− signs unreadable on long
  // lines. Solid colours give the sticky cells an opaque underlay.
  context: "bg-card",
  added: "bg-[oklch(0.92_0.05_150)] dark:bg-[oklch(0.27_0.05_150)]",
  removed: "bg-[oklch(0.92_0.05_30)] dark:bg-[oklch(0.27_0.05_30)]",
  hunkHeader:
    "px-4 py-1 text-[11px] font-mono text-muted-foreground bg-muted/40 border-y sticky left-0 z-[1]",
  // Sticky-left gutter columns: line numbers + the +/- sign stay pinned
  // when long lines force horizontal scroll. `bg-inherit` propagates the
  // row's (now solid) tint so the sticky cells don't show scrolling
  // content underneath bleeding through.
  gutterNumber:
    "text-right pr-2 text-muted-foreground/70 select-none sticky z-[1] bg-inherit",
  gutterSign: "text-center select-none sticky z-[1] bg-inherit",
  content: "pl-2 pr-4 whitespace-pre",
} as const

export const wordDiff = {
  added: "bg-[oklch(0.85_0.18_150_/_0.55)] dark:bg-[oklch(0.60_0.18_150_/_0.45)] rounded-sm px-0.5",
  removed: "bg-[oklch(0.85_0.18_30_/_0.55)] dark:bg-[oklch(0.60_0.18_30_/_0.45)] rounded-sm px-0.5",
} as const
