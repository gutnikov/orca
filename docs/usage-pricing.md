# Usage Pricing Recap

Orca keeps CLI agents running in interactive tmux sessions. Usage and price data is collected only from each agent's on-disk session artifacts, then normalized into the run's `sessions.json`. The TUI and web UI read that manifest and show a price when `usage.cost_usd` is available.

## Display Rules

Each session entry may include:

```json
{
  "usage": {
    "source": "opencode",
    "cost_usd": 0.42,
    "cost_kind": "exact",
    "tokens": {
      "input": 10,
      "output": 20,
      "reasoning": 3,
      "cache_read": 4,
      "cache_write": 5
    },
    "total_tokens": 42
  }
}
```

The UI renders:

- `$0.42 · 42 tok` when `cost_kind` is `exact` and tokens are available.
- `~$0.42 · 42 tok` when `cost_kind` is `estimated` and tokens are available.
- `42 tok`, `1.2k tok`, or similar when no cost is available but tokens are available.

## Source Data

`opencode`

Orca reads `~/.local/share/opencode/opencode.db`. The `session` table already stores `cost`, `model`, and token columns:

- `tokens_input`
- `tokens_output`
- `tokens_reasoning`
- `tokens_cache_read`
- `tokens_cache_write`

Because opencode calculates and persists the dollar cost itself, Orca treats this as exact spend and writes `cost_kind: "exact"`.

`claude-code`

Orca scans Claude Code JSONL transcripts under `~/.claude/projects/<sanitized-cwd>/*.jsonl`. Claude's sanitized cwd can replace punctuation such as `/`, `.`, and `_` with `-`, so Orca checks both the simple slash replacement and the fully normalized variant. Assistant messages include `message.model` and `message.usage`, so Orca can collect exact token counts. Claude interactive transcripts do not provide a final `total_cost_usd` field in the same way `claude -p --output-format json` does, and Orca is intentionally not using print mode. Therefore dollar cost is estimated only when a local price table is configured.

`codex`

Orca scans Codex JSONL transcripts under `~/.codex/sessions/YYYY/MM/DD/*.jsonl`. These files include:

- `session_meta.payload.cwd`
- `turn_context.payload.model`
- `event_msg.payload.type == "token_count"`
- `event_msg.payload.info.total_token_usage`

Orca uses token-count deltas after the Orca usage marker, so the collected tokens correspond to that workflow step. Codex does not persist a dollar cost in the CLI session file, so dollar cost is estimated only when a local price table is configured.

## Session Matching

Every worker prompt includes an internal marker:

```text
ORCA_USAGE_SESSION:<orca-session-id>
```

Collectors use that marker, plus the worktree path and start time, to match an Orca workflow step to the agent's external session artifact. This avoids relying only on timestamps, which can be ambiguous when multiple workers run in parallel.

For runs created before Orca wrote usage markers and worker metadata into `sessions.json`, Orca can still attempt a best-effort fallback: it infers the worker kind from the workflow config and matches transcripts by worktree path plus the session start/completion window. Marker-based matching remains preferred.

## Price Rates

Orca does not fetch model price rates from the internet at runtime. That is intentional because provider pricing changes and the CLIs do not expose a stable pricing API for all agents.

For `opencode`, rates are not needed. Orca reads the already-computed `cost` from opencode's local database.

For `claude-code` and `codex`, Orca can estimate dollar cost from a price table. The lookup order is:

1. `ORCA_USAGE_PRICES_JSON`
2. `ORCA_USAGE_PRICES_FILE`
3. Orca's built-in fallback table for common models

Example:

```json
{
  "claude-haiku-4-5": {
    "input": 1.0,
    "output": 5.0,
    "cache_read": 0.1,
    "cache_write": 1.25
  },
  "claude-sonnet-4-6": {
    "input": 3.0,
    "output": 15.0,
    "cache_read": 0.3,
    "cache_write": 3.75
  },
  "claude-opus-4-6": {
    "input": 5.0,
    "output": 25.0,
    "cache_read": 0.5,
    "cache_write": 6.25
  },
  "claude-opus-4-7": {
    "input": 5.0,
    "output": 25.0,
    "cache_read": 0.5,
    "cache_write": 6.25
  },
  "gpt-5.5": {
    "input": 1.25,
    "output": 10.0,
    "cache_read": 0.125
  }
}
```

Rates are USD per 1 million tokens. `input` and `output` are required. `cache_read` and `cache_write` are optional; when omitted, Orca falls back to the input rate for those token categories.

The built-in table is deliberately small and overrideable. Configure `ORCA_USAGE_PRICES_JSON` or `ORCA_USAGE_PRICES_FILE` when your provider pricing differs from Orca's fallback table.

Claude Code may persist provider-specific model IDs such as `us.anthropic.claude-haiku-4-5-20251001-v1:0`. Orca normalizes common provider prefixes, dated model suffixes, and `-v1:0` revisions before price lookup, so that example resolves to `claude-haiku-4-5`.

For Codex and any source where `input` includes cached tokens, the estimate formula is:

```text
billable_input = max(input - cache_read - cache_write, 0)
output_total = output + reasoning

cost_usd = (
  billable_input * input_rate
  + output_total * output_rate
  + cache_read * cache_read_rate
  + cache_write * cache_write_rate
) / 1_000_000
```

For Claude Code, `message.usage.input_tokens` is already the non-cache input count, with cache creation/read reported in separate fields, so Orca uses:

```text
billable_input = input
```

Because these costs depend on locally configured rates, the UI prefixes estimated values with `~$`.
