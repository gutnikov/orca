import type { ButtonHTMLAttributes, ReactNode } from "react"
import { cn } from "@/lib/utils"

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
  variant?: "default" | "destructive"
}

export function RunActionButton({ children, variant = "default", className, ...rest }: Props) {
  return (
    <button
      type="button"
      {...rest}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-medium",
        "transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
        variant === "default"
          ? "border-border bg-card hover:bg-muted text-foreground"
          : "border-destructive/40 bg-destructive/5 hover:bg-destructive/10 text-destructive",
        className,
      )}
    >
      {children}
    </button>
  )
}
