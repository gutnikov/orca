export function formatDuration(startedIso: string, endedIso: string | null | undefined): string {
  if (!startedIso) return ""
  const start = Date.parse(startedIso)
  if (Number.isNaN(start)) return ""
  const end = endedIso ? Date.parse(endedIso) : Date.now()
  if (Number.isNaN(end)) return ""
  const totalSeconds = Math.max(0, Math.floor((end - start) / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60)
    const remMin = minutes % 60
    return `${hours}h ${remMin}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, "0")}s`
  }
  return `${seconds}s`
}
