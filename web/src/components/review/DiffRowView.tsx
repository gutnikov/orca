import { Highlight, themes, type Language } from "prism-react-renderer"
import { MessageSquarePlus } from "lucide-react"
import { cn } from "@/lib/utils"
import { rowStyles, wordDiff } from "./diff-viewer-styles"
import type { HunkRow } from "./types"
import { diffWordsWithSpace, type Change } from "diff"
import { useIsDark } from "./useIsDark"

type Props = {
  row: HunkRow
  language?: string
  pairedWith?: HunkRow
  onAddComment?: () => void
  showGutterButton?: boolean
}

function inlineDiff(removed: string, added: string): { left: Change[]; right: Change[] } {
  const parts = diffWordsWithSpace(removed, added)
  const left: Change[] = []
  const right: Change[] = []
  for (const p of parts) {
    if (p.added) right.push(p)
    else if (p.removed) left.push(p)
    else {
      left.push(p)
      right.push(p)
    }
  }
  return { left, right }
}

function renderWordDiffParts(parts: Change[], side: "left" | "right") {
  return parts.map((p, i) => {
    if (p.added && side === "right") {
      return (
        <span key={i} className={wordDiff.added}>
          {p.value}
        </span>
      )
    }
    if (p.removed && side === "left") {
      return (
        <span key={i} className={wordDiff.removed}>
          {p.value}
        </span>
      )
    }
    if (p.added || p.removed) return null
    return <span key={i}>{p.value}</span>
  })
}

function renderHighlighted(text: string, language: string | undefined, dark: boolean) {
  const lang = (language ?? "tsx") as Language
  const theme = dark ? themes.vsDark : themes.github
  return (
    <Highlight code={text} language={lang} theme={theme}>
      {({ tokens, getTokenProps }) => (
        <>
          {tokens[0]?.map((token, i) => <span key={i} {...getTokenProps({ token })} />)}
        </>
      )}
    </Highlight>
  )
}

export function DiffRowView({
  row,
  language,
  pairedWith,
  onAddComment,
  showGutterButton = true,
}: Props) {
  const dark = useIsDark()
  const styleBucket =
    row.type === "added" ? rowStyles.added : row.type === "removed" ? rowStyles.removed : rowStyles.context
  const sign = row.type === "added" ? "+" : row.type === "removed" ? "−" : ""

  let content: React.ReactNode
  if (pairedWith && row.type === "added") {
    const { right } = inlineDiff(pairedWith.text, row.text)
    content = renderWordDiffParts(right, "right")
  } else if (pairedWith && row.type === "removed") {
    const { left } = inlineDiff(row.text, pairedWith.text)
    content = renderWordDiffParts(left, "left")
  } else {
    content = renderHighlighted(row.text, language, dark)
  }

  return (
    <div className={cn(rowStyles.base, styleBucket)}>
      {/* Sticky-left columns — explicit left offsets match the grid track
          widths above (3rem, 3rem, 2rem). Together they pin the gutter while
          long lines scroll horizontally inside the wrapper. */}
      <span className={cn(rowStyles.gutterNumber, "left-0")}>{row.oldLine ?? ""}</span>
      <span className={cn(rowStyles.gutterNumber, "left-[3rem]")}>{row.newLine ?? ""}</span>
      <span className={cn(rowStyles.gutterSign, "relative left-[6rem]")}>
        {showGutterButton ? (
          <button
            type="button"
            onClick={onAddComment}
            className={cn(
              "absolute inset-0 flex items-center justify-center",
              "opacity-0 group-hover/row:opacity-100 transition-opacity",
              "text-primary hover:bg-primary/10 rounded",
            )}
            aria-label="Add comment"
          >
            <MessageSquarePlus size={12} />
          </button>
        ) : null}
        <span className="opacity-100 group-hover/row:opacity-0 transition-opacity pointer-events-none">{sign}</span>
      </span>
      <span className={rowStyles.content}>{content}</span>
    </div>
  )
}
