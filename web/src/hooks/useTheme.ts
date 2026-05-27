import { useCallback, useSyncExternalStore } from "react"

type Theme = "light" | "dark"

const STORAGE_KEY = "orca-theme"

function getSystemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function getStoredTheme(): Theme | null {
  const v = localStorage.getItem(STORAGE_KEY)
  return v === "light" || v === "dark" ? v : null
}

function getEffectiveTheme(): Theme {
  return getStoredTheme() ?? getSystemTheme()
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark")
}

let listeners: Array<() => void> = []
function subscribe(cb: () => void) {
  listeners.push(cb)
  return () => {
    listeners = listeners.filter((l) => l !== cb)
  }
}
function notify() {
  listeners.forEach((l) => l())
}

// Apply initial theme immediately (before React hydrates)
applyTheme(getEffectiveTheme())

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getEffectiveTheme)

  const toggle = useCallback(() => {
    const next: Theme = getEffectiveTheme() === "dark" ? "light" : "dark"
    localStorage.setItem(STORAGE_KEY, next)
    applyTheme(next)
    notify()
  }, [])

  return { theme, toggle }
}
