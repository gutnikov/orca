import { useEffect, useState } from "react"
import { Moon, Sun } from "lucide-react"

function readInitialIsDark(): boolean {
  if (typeof document === "undefined") return false
  const stored = window.localStorage.getItem("orca-theme")
  if (stored === "dark") return true
  if (stored === "light") return false
  return window.matchMedia("(prefers-color-scheme: dark)").matches
}

function applyTheme(isDark: boolean) {
  document.documentElement.classList.toggle("dark", isDark)
  window.localStorage.setItem("orca-theme", isDark ? "dark" : "light")
}

export function ThemeToggle() {
  const [isDark, setIsDark] = useState<boolean>(false)

  useEffect(() => {
    const initial = readInitialIsDark()
    applyTheme(initial)
    setIsDark(initial)
  }, [])

  const toggle = () => {
    const next = !isDark
    applyTheme(next)
    setIsDark(next)
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="fixed top-4 right-4 z-50 inline-flex items-center gap-1.5 h-8 px-3 rounded-full border bg-card/90 backdrop-blur-sm text-xs font-medium text-foreground hover:bg-card transition-colors shadow-sm"
    >
      {isDark ? <Sun size={14} /> : <Moon size={14} />}
      <span>{isDark ? "Light" : "Dark"}</span>
    </button>
  )
}
