export const rowStyles = {
  // Long unbroken lines should widen the row inside the overflow container,
  // not paint outside a fixed-width row. `w-max min-w-full` keeps short rows
  // full-width while allowing long rows to extend under horizontal scroll.
  base: "group/row grid w-max min-w-full grid-cols-[3rem_3rem_2rem_max-content] gap-0 font-mono text-[12px] leading-5 min-h-5",
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
  fullBase: "group/row grid w-max min-w-full grid-cols-[3rem_2rem_max-content] gap-0 font-mono text-[12px] leading-5 min-h-5",
} as const

export const wordDiff = {
  added: "bg-[oklch(0.85_0.18_150_/_0.55)] dark:bg-[oklch(0.60_0.18_150_/_0.45)] rounded-sm px-0.5",
  removed: "bg-[oklch(0.85_0.18_30_/_0.55)] dark:bg-[oklch(0.60_0.18_30_/_0.45)] rounded-sm px-0.5",
} as const
