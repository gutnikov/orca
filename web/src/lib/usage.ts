import type { UsageState } from "@/hooks/useRunState"

export function formatUsage(usage: UsageState | null | undefined): string | null {
  if (!usage) return null
  const total = usage.total_tokens ?? tokenTotal(usage.tokens)
  const tokenText = total && total > 0 ? `${formatTokens(total)} tok` : null

  if (typeof usage.cost_usd === "number") {
    const prefix = usage.cost_kind === "estimated" ? "~$" : "$"
    const costText = `${prefix}${formatCost(usage.cost_usd)}`
    return tokenText ? `${costText} · ${tokenText}` : costText
  }
  return tokenText
}

function formatCost(value: number): string {
  if (value >= 1) return value.toFixed(2)
  if (value >= 0.01) return value.toFixed(2)
  return value.toFixed(4)
}

export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return String(value)
}

function tokenTotal(tokens: UsageState["tokens"] | undefined): number | null {
  if (!tokens) return null
  return Object.values(tokens).reduce((sum, value) => sum + value, 0)
}
