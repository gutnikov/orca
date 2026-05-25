import { useState } from "react"
import { Highlight, themes, type Language } from "prism-react-renderer"
import { ChevronDown, ChevronRight, MessageSquarePlus, X } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"

import { useIsDark } from "./useIsDark"
import { PrettyResultView } from "./PrettyResultView"
import type { InlineComment } from "./useDraftComments"

interface VirtualFileCardProps {
  id: string
  label: string
  content: string
  language: "markdown" | "json" | "yaml" | "plain"
  comments: InlineComment[]
  onAddComment: (c: Omit<InlineComment, "id"> & Partial<Pick<InlineComment, "id">>) => void
  onRemoveComment: (idx: number) => void
  /** Anchor id used for sidebar click-to-scroll. Falls back to `id` if not provided. */
  anchorId?: string
  /** Controlled collapsed state. If provided, `onToggleCollapsed` must be too. */
  collapsed?: boolean
  onToggleCollapsed?: () => void
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

// Languages that wrap long lines in source view. JSON results often contain
// long single-line strings that are unreadable when forced to horizontal scroll
// — wrap them. YAML preserves indentation alignment and reads better with scroll.
const WRAP_LANGUAGES: ReadonlySet<VirtualFileCardProps["language"]> = new Set([
  "plain",
  "markdown",
  "json",
])

/** Compact inline composer — no shadcn Textarea (which was rendering oversized). */
function LineComposer({
  fileId,
  line,
  onAdd,
  onCancel,
}: {
  fileId: string
  line: number
  onAdd: (c: Omit<InlineComment, "id"> & Partial<Pick<InlineComment, "id">>) => void
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
    <div className="bg-muted/30 border-y border-border/60 px-3 py-2.5 flex flex-col gap-2">
      <textarea
        autoFocus
        rows={2}
        className={cn(
          "w-full px-3 py-2 text-[13px] font-sans resize-none",
          "bg-background border border-border rounded-md",
          "placeholder:text-muted-foreground/70",
          "focus:outline-none focus:ring-1 focus:ring-ring focus:border-ring",
        )}
        placeholder="Leave a comment… (⌘↵ to submit, Esc to cancel)"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel()
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit()
        }}
      />
      <div className="flex gap-1.5 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 h-7 text-[12px] rounded-md border border-border bg-background hover:bg-muted cursor-pointer transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={!body.trim()}
          onClick={submit}
          className="px-3 h-7 text-[12px] rounded-md border border-primary bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Add comment
        </button>
      </div>
    </div>
  )
}

function CommentList({
  comments,
  onRemoveComment,
}: {
  comments: Array<{ comment: InlineComment; globalIdx: number }>
  onRemoveComment: (idx: number) => void
}) {
  return (
    <>
      {comments.map(({ comment, globalIdx }) => (
        <div
          key={globalIdx}
          className="border-l-2 border-primary/60 mx-3 my-2 px-3 py-2 bg-primary/5 rounded flex items-start gap-2"
        >
          <span className="flex-1 text-[13px] text-foreground whitespace-pre-wrap font-sans break-words">
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
    </>
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
  anchorId,
  collapsed: collapsedProp,
  onToggleCollapsed,
}: VirtualFileCardProps) {
  const isDark = useIsDark()
  const [composingLine, setComposingLine] = useState<number | null>(null)
  const [localCollapsed, setLocalCollapsed] = useState(false)
  const collapsed = collapsedProp ?? localCollapsed
  const toggleCollapsed =
    onToggleCollapsed ?? (() => setLocalCollapsed((v) => !v))
  // Languages that have a "rendered" view (Markdown → react-markdown,
  // JSON → PrettyResultView). YAML stays source-only — it's already readable
  // when syntax-highlighted, and there's no obvious "pretty" interpretation.
  const supportsRendered = language === "markdown" || language === "json"
  const [renderedMode, setRenderedMode] = useState<boolean>(supportsRendered)

  // Comments anchored to this file, indexed by line number.
  const commentsByLine = new Map<number, Array<{ comment: InlineComment; globalIdx: number }>>()
  const fileLevelComments: Array<{ comment: InlineComment; globalIdx: number }> = []
  comments.forEach((c, globalIdx) => {
    if (c.file !== id) return
    if (c.line === null) {
      fileLevelComments.push({ comment: c, globalIdx })
    } else {
      const bucket = commentsByLine.get(c.line) ?? []
      bucket.push({ comment: c, globalIdx })
      commentsByLine.set(c.line, bucket)
    }
  })

  const commentCount = comments.filter((c) => c.file === id).length
  const prismLang = LANGUAGE_MAP[language]
  const totalLines = content.split("\n").length
  const wrap = WRAP_LANGUAGES.has(language)

  const showRenderedToggle = supportsRendered
  const renderedLabel = language === "json" ? "Pretty" : "Rendered"

  return (
    <div id={anchorId ?? id} className="rounded-lg border border-border bg-card overflow-hidden scroll-mt-6">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/30">
        <button
          type="button"
          onClick={toggleCollapsed}
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
        <div className="ml-auto flex items-center gap-2">
          {showRenderedToggle ? (
            <div className="inline-flex border border-border rounded-md overflow-hidden text-[11px]">
              <button
                type="button"
                onClick={() => setRenderedMode(true)}
                className={cn(
                  "px-2 py-0.5 cursor-pointer transition-colors",
                  renderedMode
                    ? "bg-accent text-foreground font-semibold"
                    : "text-muted-foreground hover:bg-muted",
                )}
              >
                {renderedLabel}
              </button>
              <button
                type="button"
                onClick={() => setRenderedMode(false)}
                className={cn(
                  "px-2 py-0.5 cursor-pointer transition-colors border-l border-border",
                  !renderedMode
                    ? "bg-accent text-foreground font-semibold"
                    : "text-muted-foreground hover:bg-muted",
                )}
              >
                Source
              </button>
            </div>
          ) : null}
          {commentCount > 0 ? (
            <span className="text-[11px] text-primary font-medium bg-primary/10 px-2 py-0.5 rounded-full">
              {commentCount}
            </span>
          ) : (
            <span className="text-[11px] text-muted-foreground tabular-nums">
              {totalLines} {totalLines === 1 ? "line" : "lines"}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      {collapsed ? null : language === "json" && renderedMode ? (
        (() => {
          let parsed: unknown = null
          try {
            parsed = JSON.parse(content)
          } catch {
            return (
              <div className="px-5 py-4 text-[13px] text-muted-foreground italic">
                Could not parse result as JSON. Switch to{" "}
                <button
                  type="button"
                  className="underline underline-offset-2 hover:text-foreground cursor-pointer"
                  onClick={() => setRenderedMode(false)}
                >
                  Source
                </button>
                .
              </div>
            )
          }
          if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
            return (
              <>
                <PrettyResultView result={parsed as Record<string, unknown>} />
                {fileLevelComments.length > 0 ? (
                  <div className="mx-5 mt-2 mb-4 pt-3 border-t border-border/60">
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">
                      File-level comments
                    </div>
                    <CommentList
                      comments={fileLevelComments}
                      onRemoveComment={onRemoveComment}
                    />
                  </div>
                ) : null}
                <div className="px-5 pb-4 text-[11.5px] text-muted-foreground">
                  Switch to{" "}
                  <button
                    type="button"
                    className="underline underline-offset-2 hover:text-foreground cursor-pointer"
                    onClick={() => setRenderedMode(false)}
                  >
                    Source
                  </button>{" "}
                  to comment on specific lines.
                </div>
              </>
            )
          }
          // Top-level array or scalar — just stringify nicely
          return (
            <div className="px-5 py-4">
              <pre className="text-[13px] font-mono whitespace-pre-wrap break-words bg-muted/30 border border-border/60 rounded-md px-3 py-2">
                {JSON.stringify(parsed, null, 2)}
              </pre>
            </div>
          )
        })()
      ) : language === "markdown" && renderedMode ? (
        <div className="px-6 py-5">
          <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:font-semibold prose-headings:tracking-tight prose-pre:bg-muted prose-pre:text-foreground prose-code:before:hidden prose-code:after:hidden prose-table:border prose-th:bg-muted prose-th:px-3 prose-th:py-2 prose-td:border prose-td:px-3 prose-td:py-2 prose-a:text-primary">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
          {fileLevelComments.length > 0 ? (
            <div className="mt-4 pt-4 border-t border-border/60">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">
                File-level comments
              </div>
              <CommentList
                comments={fileLevelComments}
                onRemoveComment={onRemoveComment}
              />
            </div>
          ) : null}
          <div className="mt-4 pt-4 border-t border-border/60 text-[11.5px] text-muted-foreground">
            Switch to <button
              type="button"
              className="underline underline-offset-2 hover:text-foreground cursor-pointer"
              onClick={() => setRenderedMode(false)}
            >Source</button> to comment on specific lines.
          </div>
        </div>
      ) : (
        <Highlight code={content} language={prismLang} theme={isDark ? themes.vsDark : themes.github}>
          {({ tokens, getLineProps, getTokenProps, style }) => (
            <div
              className={cn(
                "font-mono text-[12.5px] leading-[1.65]",
                !wrap && "overflow-x-auto",
              )}
              style={{ background: style.background, color: style.color }}
            >
              {tokens.map((line, idx) => {
                const lineNumber = idx + 1
                const lineComments = commentsByLine.get(lineNumber) ?? []
                const isComposing = composingLine === lineNumber
                const lineProps = getLineProps({ line })
                return (
                  <div key={idx}>
                    <div
                      className={cn(
                        "group flex items-start",
                        "hover:bg-muted/40 transition-colors",
                        lineComments.length > 0 && "bg-primary/[0.03]",
                      )}
                    >
                      {/* Gutter */}
                      <div
                        className={cn(
                          "select-none text-right pl-3 pr-3 py-[1px]",
                          "text-muted-foreground/60 text-[11px] tabular-nums",
                          "shrink-0 w-[3.5rem]",
                          "flex items-center justify-end gap-1",
                        )}
                      >
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
                        <span>{lineNumber}</span>
                      </div>

                      {/* Content */}
                      <div
                        className={cn(
                          "py-[1px] pr-4 pl-1 min-w-0 flex-1",
                          wrap ? "whitespace-pre-wrap" : "whitespace-pre",
                        )}
                      >
                        {line.length === 0 ? (
                          <span> </span>
                        ) : (
                          <span {...lineProps} className={cn(lineProps.className)}>
                            {line.map((token, tokenIdx) => (
                              <span key={tokenIdx} {...getTokenProps({ token })} />
                            ))}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Comments + composer */}
                    {lineComments.length > 0 || isComposing ? (
                      <div className="bg-muted/10 border-y border-border/30">
                        <CommentList
                          comments={lineComments}
                          onRemoveComment={onRemoveComment}
                        />
                        {isComposing ? (
                          <LineComposer
                            fileId={id}
                            line={lineNumber}
                            onAdd={onAddComment}
                            onCancel={() => setComposingLine(null)}
                          />
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          )}
        </Highlight>
      )}
    </div>
  )
}
