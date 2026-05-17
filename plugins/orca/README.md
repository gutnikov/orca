# Orca Codex Plugin

Codex plugin package for Orca. It provides:

- `orca-setup`, `orca-supervise`, and `orca-create-workflow` skills
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
