const APPROX_CHARS_PER_TOKEN = 4

export function estimatePromptTokens(text: string): number {
  const trimmed = text.trim()
  if (!trimmed) return 0
  return Math.ceil(trimmed.length / APPROX_CHARS_PER_TOKEN)
}
