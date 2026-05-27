import type { ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { cn } from "@/lib/utils"

interface AppShellProps {
  children: ReactNode
  className?: string
}

/** Page wrapper. Sets the canvas background and full-viewport min-height. */
export function AppShell({ children, className }: AppShellProps) {
  return (
    <div
      className={cn(
        "min-h-screen bg-[var(--canvas)] text-[var(--fg)] font-sans",
        className,
      )}
    >
      {children}
    </div>
  )
}

export interface BreadcrumbItem {
  label: ReactNode
  to?: string                                    // TanStack Router path
  params?: Record<string, string>                // params for `to`
  mono?: boolean                                 // render in monospace (run ids, etc.)
}

interface AppHeaderProps {
  breadcrumb: BreadcrumbItem[]
  actions?: ReactNode
}

/** Sticky top bar — logo dot, breadcrumb, right-aligned actions slot. */
export function AppHeader({ breadcrumb, actions }: AppHeaderProps) {
  return (
    <header
      className={cn(
        "sticky top-0 z-30 bg-[var(--canvas)]",
        "border-b border-[var(--border)]",
        "px-4 h-12 flex items-center gap-3",
      )}
    >
      <div className="size-6 rounded-full bg-gradient-to-br from-[#1f6feb] to-[#6e40c9] shrink-0" />
      <nav className="flex items-center gap-1 text-[13px] min-w-0">
        {breadcrumb.map((item, idx) => {
          const isLast = idx === breadcrumb.length - 1
          const content = (
            <span
              className={cn(
                item.mono ? "font-mono" : "",
                isLast ? "text-[var(--fg)] font-semibold" : "text-[var(--accent-fg)] hover:underline",
                "truncate",
              )}
            >
              {item.label}
            </span>
          )
          return (
            <span key={idx} className="flex items-center gap-1 min-w-0">
              {item.to ? (
                <Link to={item.to} params={item.params}>
                  {content}
                </Link>
              ) : (
                content
              )}
              {!isLast && (
                <span className="text-[var(--border)] select-none mx-0.5">/</span>
              )}
            </span>
          )
        })}
      </nav>
      {actions && (
        <div className="ml-auto flex items-center gap-2 shrink-0">{actions}</div>
      )}
    </header>
  )
}
