import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

interface Props {
  icon: ReactNode
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon, title, description, action, className }: Props) {
  return (
    <div
      className={cn(
        "rounded-md border border-[var(--border)] bg-[var(--surface)]",
        "px-6 py-8 text-center",
        className,
      )}
    >
      <div
        className={cn(
          "inline-flex items-center justify-center size-14 rounded-full",
          "bg-[var(--subtle)] text-[var(--fg-muted)] mb-3.5",
        )}
      >
        {icon}
      </div>
      <h4 className="text-[14px] font-semibold text-[var(--fg)]">{title}</h4>
      {description && (
        <p className="mt-1 text-[12px] text-[var(--fg-muted)]">{description}</p>
      )}
      {action && <div className="mt-3.5">{action}</div>}
    </div>
  )
}
