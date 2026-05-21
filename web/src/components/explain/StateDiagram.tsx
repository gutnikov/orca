import { useEffect, useRef, useState } from "react"
import { useIsDark } from "./useIsDark"
import { Card } from "@/components/ui/card"

// Mermaid's color parser doesn't understand oklch() — the project's design
// tokens are oklch-based. Rather than runtime-converting tokens (which is
// fragile across browsers), we keep two hand-tuned palettes that mirror the
// `light` and `dark` token values closely enough.
const LIGHT_PALETTE = {
  fontFamily: "Open Sans, sans-serif",
  primaryColor: "#f7f7f7",       // ~ --card light
  primaryTextColor: "#1a1a2e",    // ~ --foreground light
  primaryBorderColor: "#d4d4d8",  // ~ --border light
  lineColor: "#1a1a2e",
  secondaryColor: "#f0f0f0",      // ~ --muted light
  tertiaryColor: "#ffffff",
  background: "#fafafa",          // ~ --background light
  mainBkg: "#ffffff",
  nodeTextColor: "#1a1a2e",
} as const

const DARK_PALETTE = {
  fontFamily: "Open Sans, sans-serif",
  primaryColor: "#262626",        // ~ --card dark
  primaryTextColor: "#e5e5e5",    // ~ --foreground dark
  primaryBorderColor: "#404460",  // ~ --border dark
  lineColor: "#e5e5e5",
  secondaryColor: "#2a2a2a",      // ~ --muted dark
  tertiaryColor: "#262626",
  background: "#000000",          // ~ --background dark
  mainBkg: "#1f1f1f",
  nodeTextColor: "#e5e5e5",
} as const

function themeVariables(dark: boolean) {
  return dark ? DARK_PALETTE : LIGHT_PALETTE
}

function replaceChildren(target: HTMLElement, svgMarkup: string) {
  // Safe DOM mount: parse the Mermaid SVG with DOMParser and adopt it
  // into the live document instead of assigning .innerHTML directly.
  const parsed = new DOMParser().parseFromString(svgMarkup, "image/svg+xml")
  const svgEl = parsed.documentElement
  while (target.firstChild) target.removeChild(target.firstChild)
  target.appendChild(document.adoptNode(svgEl))
}

export function StateDiagram({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const dark = useIsDark()
  const [error, setError] = useState<string | null>(null)
  const [renderId] = useState(() => `mermaid-${Math.random().toString(36).slice(2, 10)}`)

  useEffect(() => {
    let cancelled = false
    setError(null)

    ;(async () => {
      try {
        const mermaid = (await import("mermaid")).default
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: themeVariables(dark),
        })
        const { svg } = await mermaid.render(renderId, source)
        if (cancelled) return
        const target = ref.current
        if (target) replaceChildren(target, svg)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    })()

    return () => {
      cancelled = true
    }
  }, [source, dark, renderId])

  if (error) {
    return (
      <Card className="p-4 text-sm space-y-2">
        <div className="text-destructive font-semibold">Diagram failed to render</div>
        <div className="text-xs text-muted-foreground">{error}</div>
        <pre className="text-xs font-mono bg-muted/40 p-2 rounded-md overflow-x-auto whitespace-pre">{source}</pre>
      </Card>
    )
  }

  return (
    <Card className="p-4 overflow-x-auto">
      <div ref={ref} className="flex justify-center [&_svg]:max-w-full [&_svg]:h-auto" />
    </Card>
  )
}
