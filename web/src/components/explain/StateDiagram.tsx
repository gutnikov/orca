import { useEffect, useRef, useState } from "react"
import { useIsDark } from "./useIsDark"
import { Card } from "@/components/ui/card"

function readToken(name: string): string {
  if (typeof document === "undefined") return ""
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function themeVariables() {
  const fontSans = readToken("--font-sans") || "Open Sans, sans-serif"
  return {
    fontFamily: fontSans,
    primaryColor: readToken("--card") || "#fff",
    primaryTextColor: readToken("--foreground") || "#000",
    primaryBorderColor: readToken("--border") || "#999",
    lineColor: readToken("--foreground") || "#666",
    secondaryColor: readToken("--muted") || "#eee",
    tertiaryColor: readToken("--card") || "#fff",
    background: readToken("--background") || "#fff",
    mainBkg: readToken("--card") || "#fff",
    nodeTextColor: readToken("--foreground") || "#000",
  }
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
          theme: dark ? "dark" : "base",
          themeVariables: themeVariables(),
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
