import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  cn(
    "inline-flex shrink-0 items-center justify-center gap-1.5",
    "rounded-md font-medium whitespace-nowrap",
    "border transition-colors duration-[120ms]",
    "outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
    "disabled:pointer-events-none disabled:opacity-40 disabled:cursor-not-allowed",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ),
  {
    variants: {
      variant: {
        // GitHub-green primary, for affirmative actions only (Start run, Save).
        primary:
          "bg-[#238636] border-[#238636] text-white hover:bg-[#2ea043] hover:border-[#2ea043]",
        // Default — bordered overlay, the most common variant.
        default:
          "bg-[var(--overlay)] border-[var(--border)] text-[var(--fg)] hover:bg-[#30363d] hover:border-[#8d96a080]",
        // Outlined red, transparent fill until hover. For Stop / Drop.
        danger:
          "bg-transparent border-[var(--border)] text-[var(--danger)] hover:bg-[#f8514914] hover:border-[var(--danger)]",
        // Borderless, low-priority. For Cancel buttons in modals.
        ghost:
          "bg-transparent border-transparent text-[var(--fg-muted)] hover:bg-[var(--overlay)] hover:text-[var(--fg)]",
      },
      size: {
        md: "h-7 px-3 text-[12px]",
        sm: "h-6 px-2.5 text-[11px] gap-1 [&_svg:not([class*='size-'])]:size-3.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  },
)

function Button({
  className,
  variant = "default",
  size = "md",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"
  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
