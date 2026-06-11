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
    let inFlight = false
    let timer: ReturnType<typeof setInterval> | null = null

    const tick = () => {
      // Skip this tick while the previous callback is still pending — a slow
      // daemon must not pile up overlapping requests whose stale responses
      // could overwrite fresher data.
      if (cancelled || inFlight) return
      inFlight = true
      Promise.resolve()
        .then(() => callbackRef.current())
        .catch(() => {})
        .finally(() => {
          inFlight = false
        })
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
