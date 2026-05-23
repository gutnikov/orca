import { useState } from "react"
import { Highlight, themes, type Language } from "prism-react-renderer"
import { ChevronDown, ChevronRight, MessageSquarePlus, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

import { useIsDark } from "./useIsDark"
import type { InlineComment } from "./useDraftComments"

interface VirtualFileCardProps {
  id: string
  label: string
  content: string
  language: "markdown" | "json" | "yaml" | "plain"
  comments: InlineComment[]
  onAddComment: (c: InlineComment) => void
  onRemoveComment: (idx: number) => void
}

const LANGUAGE_MAP: Record<VirtualFileCardProps["language"], Language> = {
  markdown: "markdown",
  json: "json",
  yaml: "yaml",
  plain: "tsx",
}

const LANGUAGE_LABEL: Record<VirtualFileCardProps["language"], string> = {
  markdown: "Markdown",
  json: "JSON",
  yaml: "YAML",
  plain: "Text",
}

/** Inline mini-composer that appears below a specific line. */
function LineComposer({
  fileId,
  line,
  onAdd,
  onCancel,
}: {
  fileId: string
  line: number
  onAdd: (c: InlineComment) => void
  onCancel: () => void
}) {
  const [body, setBody] = useState("")
  const submit = () => {
    if (body.trim()) {
      onAdd({ file: fileId, line, body: body.trim() })
      onCancel()
    }
  }
  return (
    <div className="bg-muted/40 border-y border-border/60 px-4 py-3 flex flex-col gap-2">
      <Textarea
        autoFocus
        rows={2}
        className="text-[13px] font-sans resize-none bg-background"
        placeholder="Leave a comment… (⌘↵ to submit)"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel()
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit()
        }}
      />
      <div className="flex gap-1 justify-end">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="button" size="sm" disabled={!body.trim()} onClick={submit}>
          Add comment
        </Button>
      </div>
    </div>
  )
}

export function VirtualFileCard({
  id,
  label,
  content,
  language,
  comments,
  onAddComment,
  onRemoveComment,
}: VirtualFileCardProps) {
  const isDark = useIsDark()
  const [composingLine, setComposingLine] = useState<number | null>(null)
  const [collapsed, setCollapsed] = useState(false)

  // Comments anchored to this file, indexed by line number
  const commentsByLine = new Map<number, Array<{ comment: InlineComment; globalIdx: number }>>()
  comments.forEach((c, globalIdx) => {
    if (c.file === id && c.line !== null) {
      const bucket = commentsByLine.get(c.line) ?? []
      bucket.push({ comment: c, globalIdx })
      commentsByLine.set(c.line, bucket)
    }
  })

  const commentCount = comments.filter((c) => c.file === id).length
  const prismLang = LANGUAGE_MAP[language]
  const lines = content.split("\n")

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/30">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
          aria-label={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
        </button>
        <span className="font-mono text-[13px] font-semibold truncate">{label}</span>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground bg-muted/60 border border-border/60 px-1.5 py-0.5 rounded font-medium">
          {LANGUAGE_LABEL[language]}
        </span>
        <span className="text-[11px] text-muted-foreground/80">virtual</span>
        {commentCount > 0 ? (
          <span className="ml-auto text-[11px] text-primary font-medium bg-primary/10 px-2 py-0.5 rounded-full">
            {commentCount} {commentCount === 1 ? "comment" : "comments"}
          </span>
        ) : (
          <span className="ml-auto text-[11px] text-muted-foreground">
            {lines.length} {lines.length === 1 ? "line" : "lines"}
          </span>
        )}
      </div>

      {/* Body */}
      {collapsed ? null : (
        <Highlight
          code={content}
          language={prismLang}
          theme={isDark ? themes.vsDark : themes.github}
        >
          {({ tokens, getLineProps, getTokenProps, style }) => (
            <div
              className="font-mono text-[12.5px] leading-[1.55] overflow-x-auto"
              style={{ background: style.background, color: style.color }}
            >
              <table className="w-full border-collapse">
                <tbody>
                  {tokens.map((line, idx) => {
                    const lineNumber = idx + 1
                    const lineComments = commentsByLine.get(lineNumber) ?? []
                    const isComposing = composingLine === lineNumber
                    const lineProps = getLineProps({ line })
                    return (
                      <>
                        <tr
                          key={`l-${idx}`}
                          className={cn(
                            "group",
                            "hover:bg-muted/40 transition-colors",
                            lineComments.length > 0 && "bg-primary/[0.03]",
                          )}
                        >
                          <td
                            className="select-none text-right pr-3 pl-3 text-muted-foreground/60 text-[11px] sticky left-0 w-[1%] whitespace-nowrap align-top"
                            style={{ background: style.background }}
                          >
                            <div className="flex items-center justify-end gap-1 group/gutter">
                              <button
                                type="button"
                                onClick={() => setComposingLine(lineNumber)}
                                className={cn(
                                  "opacity-0 group-hover:opacity-100 transition-opacity",
                                  "inline-flex items-center justify-center w-4 h-4 rounded",
                                  "bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer",
                                )}
                                aria-label={`Comment on line ${lineNumber}`}
                              >
                                <MessageSquarePlus size={10} strokeWidth={2.5} />
                              </button>
                              <span className="tabular-nums">{lineNumber}</span>
                            </div>
                          </td>
                          <td
                            {...lineProps}
                            className={cn("pl-3 pr-4 whitespace-pre align-top", lineProps.className)}
                            style={{ ...lineProps.style }}
                          >
                            {line.length === 0 ? (
                              <span> </span>
                            ) : (
                              line.map((token, tokenIdx) => (
                                <span key={tokenIdx} {...getTokenProps({ token })} />
                              ))
                            )}
                          </td>
                        </tr>

                        {/* Inline comments and composer occupy the full row */}
                        {lineComments.length > 0 || isComposing ? (
                          <tr key={`c-${idx}`}>
                            <td
                              className="bg-muted/10 border-y border-border/30"
                              style={{ background: style.background }}
                            />
                            <td className="bg-muted/10 border-y border-border/30 p-0">
                              {lineComments.map(({ comment, globalIdx }) => (
                                <div
                                  key={globalIdx}
                                  className="border-l-2 border-primary/60 mx-3 my-2 px-3 py-2 bg-primary/5 rounded flex items-start gap-2"
                                >
                                  <span className="flex-1 text-[13px] text-foreground whitespace-pre-wrap font-sans">
                                    {comment.body}
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => onRemoveComment(globalIdx)}
                                    className="text-muted-foreground hover:text-destructive shrink-0 cursor-pointer"
                                    aria-label="Remove comment"
                                  >
                                    <X size={14} />
                                  </button>
                                </div>
                              ))}
                              {isComposing ? (
                                <LineComposer
                                  fileId={id}
                                  line={lineNumber}
                                  onAdd={onAddComment}
                                  onCancel={() => setComposingLine(null)}
                                />
                              ) : null}
                            </td>
                          </tr>
                        ) : null}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Highlight>
      )}
    </div>
  )
}
