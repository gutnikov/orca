import { useCallback, useMemo, useState } from "react"
import type { ReviewComment } from "@/lib/schema"
import type { ViewMode } from "./types"
import { draftKey } from "./types"

export type CommentSide = "old" | "new"

export type UseChangesetStateInput = {
  initialComments: ReviewComment[]
  onChange: (next: ReviewComment[]) => void
  filePaths: string[]
}

export type UseChangesetStateApi = {
  comments: ReviewComment[]
  drafts: Map<string, string>
  collapsed: Set<string>
  viewMode: Map<string, ViewMode>

  commentsForLine: (file: string, side: CommentSide, line: number) => ReviewComment[]
  draftForLine: (file: string, side: CommentSide, line: number) => string | undefined
  commentCountForFile: (file: string) => number

  openDraft: (file: string, side: CommentSide, line: number) => void
  updateDraft: (file: string, side: CommentSide, line: number, body: string) => void
  closeDraft: (file: string, side: CommentSide, line: number) => void
  saveDraft: (file: string, side: CommentSide, line: number) => void

  editComment: (index: number, body: string) => void
  deleteComment: (index: number) => void

  toggleCollapse: (file: string) => void
  collapseAll: () => void
  expandAll: () => void
  setFileMode: (file: string, mode: ViewMode) => void
}

export function useChangesetState({
  initialComments,
  onChange,
  filePaths,
}: UseChangesetStateInput): UseChangesetStateApi {
  const [comments, setComments] = useState<ReviewComment[]>(initialComments)
  const [drafts, setDrafts] = useState<Map<string, string>>(new Map())
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [viewMode, setViewMode] = useState<Map<string, ViewMode>>(
    () => new Map(filePaths.map((p) => [p, "changes" as ViewMode])),
  )

  const commit = useCallback(
    (next: ReviewComment[]) => {
      setComments(next)
      onChange(next)
    },
    [onChange],
  )

  const commentsByKey = useMemo(() => {
    const map = new Map<string, ReviewComment[]>()
    for (const c of comments) {
      const key = draftKey(c.file, c.side, c.line)
      const arr = map.get(key) ?? []
      arr.push(c)
      map.set(key, arr)
    }
    return map
  }, [comments])

  const countsByFile = useMemo(() => {
    const map = new Map<string, number>()
    for (const c of comments) map.set(c.file, (map.get(c.file) ?? 0) + 1)
    return map
  }, [comments])

  const commentsForLine = useCallback(
    (file: string, side: CommentSide, line: number) =>
      commentsByKey.get(draftKey(file, side, line)) ?? [],
    [commentsByKey],
  )

  const draftForLine = useCallback(
    (file: string, side: CommentSide, line: number) =>
      drafts.get(draftKey(file, side, line)),
    [drafts],
  )

  const commentCountForFile = useCallback(
    (file: string) => countsByFile.get(file) ?? 0,
    [countsByFile],
  )

  const openDraft = useCallback((file: string, side: CommentSide, line: number) => {
    setDrafts((prev) => {
      const next = new Map(prev)
      next.set(draftKey(file, side, line), "")
      return next
    })
  }, [])

  const updateDraft = useCallback((file: string, side: CommentSide, line: number, body: string) => {
    setDrafts((prev) => {
      const next = new Map(prev)
      next.set(draftKey(file, side, line), body)
      return next
    })
  }, [])

  const closeDraft = useCallback((file: string, side: CommentSide, line: number) => {
    setDrafts((prev) => {
      const next = new Map(prev)
      next.delete(draftKey(file, side, line))
      return next
    })
  }, [])

  const saveDraft = useCallback(
    (file: string, side: CommentSide, line: number) => {
      const key = draftKey(file, side, line)
      const body = (drafts.get(key) ?? "").trim()
      if (!body) return
      const next = [...comments, { file, side, line, body }]
      commit(next)
      setDrafts((prev) => {
        const m = new Map(prev)
        m.delete(key)
        return m
      })
    },
    [drafts, comments, commit],
  )

  const editComment = useCallback(
    (index: number, body: string) => {
      const trimmed = body.trim()
      if (!trimmed) return
      const next = comments.map((c, i) => (i === index ? { ...c, body: trimmed } : c))
      commit(next)
    },
    [comments, commit],
  )

  const deleteComment = useCallback(
    (index: number) => {
      const next = comments.filter((_, i) => i !== index)
      commit(next)
    },
    [comments, commit],
  )

  const toggleCollapse = useCallback((file: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(file)) next.delete(file)
      else next.add(file)
      return next
    })
  }, [])

  const collapseAll = useCallback(() => {
    setCollapsed(new Set(filePaths))
  }, [filePaths])

  const expandAll = useCallback(() => {
    setCollapsed(new Set())
  }, [])

  const setFileMode = useCallback((file: string, mode: ViewMode) => {
    setViewMode((prev) => {
      const next = new Map(prev)
      next.set(file, mode)
      return next
    })
  }, [])

  return {
    comments,
    drafts,
    collapsed,
    viewMode,
    commentsForLine,
    draftForLine,
    commentCountForFile,
    openDraft,
    updateDraft,
    closeDraft,
    saveDraft,
    editComment,
    deleteComment,
    toggleCollapse,
    collapseAll,
    expandAll,
    setFileMode,
  }
}
