export const rowStyles = {
  base: "group/row grid grid-cols-[3rem_3rem_2rem_1fr] gap-0 font-mono text-[12px] leading-5 min-h-5",
  context: "bg-card",
  added:
    "bg-[oklch(0.96_0.05_150_/_0.55)] dark:bg-[oklch(0.30_0.06_150_/_0.30)]",
  removed:
    "bg-[oklch(0.96_0.05_30_/_0.55)] dark:bg-[oklch(0.30_0.06_30_/_0.30)]",
  hunkHeader:
    "px-4 py-1 text-[11px] font-mono text-muted-foreground bg-muted/40 border-y",
  gutterNumber: "text-right pr-2 text-muted-foreground/70 select-none",
  gutterSign: "text-center select-none",
  content: "pl-2 pr-4 whitespace-pre overflow-x-hidden",
} as const

export const wordDiff = {
  added: "bg-[oklch(0.85_0.18_150_/_0.55)] dark:bg-[oklch(0.60_0.18_150_/_0.45)] rounded-sm px-0.5",
  removed: "bg-[oklch(0.85_0.18_30_/_0.55)] dark:bg-[oklch(0.60_0.18_30_/_0.45)] rounded-sm px-0.5",
} as const
