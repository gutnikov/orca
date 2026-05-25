import { useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Loader2, Sparkles, User } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ThreadView } from "./useCommentThreads"

export function CommentThreadView({
  commentId,
  thread,
  onReply,
}: {
  commentId: string
  thread: ThreadView | undefined
  onReply: (commentId: string, body: string) => Promise<void>
}) {
  const [composer, setComposer] = useState("")
  const [composerOpen, setComposerOpen] = useState(false)

  const handleSubmit = async () => {
    const trimmed = composer.trim()
    if (!trimmed) return
    setComposer("")
    setComposerOpen(false)
    await onReply(commentId, trimmed)
  }

  return (
    <div className="mt-1.5 pt-1.5 border-t border-primary/20 space-y-2">
      {thread?.messages.map((m) => (
        <div key={m.id} className="space-y-0.5">
          <div className={cn(
            "flex items-center gap-1.5 text-[10px] font-mono",
            m.role === "agent" ? "text-primary" : "text-muted-foreground",
          )}>
            {m.role === "agent" ? <Sparkles size={10} /> : <User size={10} />}
            <span>{m.role === "agent" ? "Orca" : "You"}</span>
          </div>
          <div className="prose prose-sm dark:prose-invert max-w-none text-[13px] [&_p]:my-1 [&_pre]:my-1 [&_ul]:my-1">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.body}</ReactMarkdown>
          </div>
        </div>
      ))}
      {thread?.agentReviewing ? (
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Loader2 size={11} className="animate-spin" />
          <span>Orca is reviewing…</span>
        </div>
      ) : null}
      {composerOpen ? (
        <div className="space-y-1.5">
          <textarea
            autoFocus
            rows={2}
            className={cn(
              "w-full px-2 py-1.5 text-[13px] font-sans resize-none",
              "bg-background border border-border rounded-md",
              "placeholder:text-muted-foreground/70",
              "focus:outline-none focus:ring-1 focus:ring-ring",
            )}
            placeholder="Reply… (⌘↵ to send, Esc to cancel)"
            value={composer}
            onChange={(e) => setComposer(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setComposerOpen(false)
                setComposer("")
              }
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void handleSubmit()
            }}
          />
          <div className="flex gap-1.5 justify-end">
            <button
              type="button"
              onClick={() => { setComposerOpen(false); setComposer("") }}
              className="px-2 h-6 text-[11px] rounded-md border border-border bg-background hover:bg-muted cursor-pointer"
            >Cancel</button>
            <button
              type="button"
              disabled={!composer.trim()}
              onClick={() => void handleSubmit()}
              className="px-2 h-6 text-[11px] rounded-md border border-primary bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer disabled:opacity-50"
            >Send</button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setComposerOpen(true)}
          className="text-[12px] text-muted-foreground hover:text-foreground cursor-pointer"
        >
          Reply…
        </button>
      )}
    </div>
  )
}
