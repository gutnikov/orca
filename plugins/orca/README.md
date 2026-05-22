# Orca Codex Plugin

Codex plugin package for Orca. It provides:

- `orca-install`, `orca-workflow-create`, `orca-workflow-run`, and `orca-prompt-create` skills
- Orca MCP server registration via `.mcp.json`
- A session hook that nudges setup when Orca is missing and starts the daemon in Orca-enabled projects

Install the marketplace from this repository:

```bash
codex plugin marketplace add gutnikov/orca
```

For local testing from a checkout:

```bash
codex plugin marketplace add /path/to/orca
```
