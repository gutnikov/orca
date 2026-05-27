import { useEffect, useRef, useState } from "react"
import { Check, ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

export type DebugAction =
  | "modify_restart"
  | "modify_continue"
  | "restart"
  | "accept"
  | "stop"

interface ActionMeta {
  label: string
  hint: string
  variant: "primary" | "default" | "danger"
}

const ACTIONS: Record<DebugAction, ActionMeta> = {
  modify_restart: {
    label: "Modify prompts & configs → restart step",
    hint: "Use my comments to update the prompt and config, then re-run this step from a clean state.",
    variant: "default",
  },
  modify_continue: {
    label: "Modify prompts & configs → continue",
    hint: "Accept this output AND update the prompt/config from my comments — improvements land for future runs without redoing this step.",
    variant: "default",
  },
  restart: {
    label: "Restart without changes",
    hint: "Re-run this step from a clean state with the same prompt — no edits.",
    variant: "default",
  },
  accept: {
    label: "Accept & continue",
    hint: "Keep this output and move on to the next step in the workflow.",
    variant: "primary",
  },
  stop: {
    label: "Stop run",
    hint: "Stop the run here. The worker's changes are kept on disk so you can inspect them.",
    variant: "danger",
  },
}

interface ActionButtonProps {
  defaultAction?: DebugAction
  onSubmit: (action: DebugAction) => void
  disabled?: boolean
}

export function ActionButton({
  defaultAction = "accept",
  onSubmit,
  disabled,
}: ActionButtonProps) {
  const [selected, setSelected] = useState<DebugAction>(defaultAction)
  const [open, setOpen] = useState(false)
  const meta = ACTIONS[selected]
  const containerRef = useRef<HTMLDivElement>(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onClick)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onClick)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  return (
    <div ref={containerRef} className="flex flex-col items-end gap-1.5 relative">
      <div className="inline-flex shadow-sm">
        <Button
          type="button"
          variant={meta.variant}
          size="md"
          onClick={() => onSubmit(selected)}
          disabled={disabled}
          className="px-4 text-[13px] font-semibold tracking-tight rounded-r-none border-r-0 h-9"
        >
          {meta.label}
        </Button>
        <Button
          type="button"
          variant={meta.variant}
          size="md"
          onClick={() => setOpen((o) => !o)}
          disabled={disabled}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="Pick another action"
          className="px-2 h-9 rounded-l-none border-l-[var(--border-split,rgba(255,255,255,0.15))]"
        >
          <ChevronDown
            size={14}
            strokeWidth={2.5}
            className={cn("transition-transform", open && "rotate-180")}
          />
        </Button>
      </div>
      {open ? (
        <div
          role="menu"
          className={cn(
            "absolute top-full mt-1.5 right-0 z-20 min-w-[300px]",
            "bg-[var(--overlay)] text-[var(--fg)] border border-[var(--border)] rounded-md shadow-lg",
            "py-1 overflow-hidden",
          )}
        >
          {(Object.keys(ACTIONS) as DebugAction[]).map((a) => {
            const isSelected = a === selected
            const itemMeta = ACTIONS[a]
            return (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={isSelected}
                key={a}
                onClick={() => {
                  setSelected(a)
                  setOpen(false)
                }}
                className={cn(
                  "w-full text-left px-3 py-2 text-[13px] flex items-start gap-2.5 cursor-pointer",
                  "hover:bg-[var(--accent-soft)] hover:text-[var(--fg)] transition-colors",
                  isSelected && "bg-[var(--accent-soft)]",
                )}
              >
                <span className="w-3.5 shrink-0 mt-0.5 text-[var(--accent-fg)]">
                  {isSelected ? <Check size={14} strokeWidth={2.5} /> : null}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block font-semibold">{itemMeta.label}</span>
                  <span className="block text-[11.5px] text-[var(--fg-muted)] mt-0.5 leading-snug">
                    {itemMeta.hint}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
