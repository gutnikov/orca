import { useEffect, useRef } from "react"

/**
 * Run `callback` immediately and then every `intervalMs` while the tab is
 * visible. Pauses on document.visibilitychange (hidden), resumes on visible.
 *
 * The callback is stored in a ref so callers can capture fresh closure state
 * without re-installing the interval on every render.
 */
export function usePollInterval(
  callback: () => void | Promise<void>,
  intervalMs: number,
  enabled = true,
): void {
  const callbackRef = useRef(callback)
  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | null = null

    const tick = () => {
      if (cancelled) return
      void callbackRef.current()
    }

    const start = () => {
      if (timer !== null || document.hidden) return
      tick()
      timer = setInterval(tick, intervalMs)
    }

    const stop = () => {
      if (timer !== null) {
        clearInterval(timer)
        timer = null
      }
    }

    const onVisibility = () => {
      if (document.hidden) stop()
      else start()
    }

    start()
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      cancelled = true
      stop()
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [intervalMs, enabled])
}
