from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    return cast("dict[str, Any]", data)


def test_claude_plugin_manifest_paths_exist() -> None:
    manifest_path = ROOT / "plugin/orca/.claude-plugin/plugin.json"
    manifest = _read_json(manifest_path)

    assert manifest["name"] == "orca"
    assert (manifest_path.parent.parent / "skills/orca-setup/SKILL.md").exists()
    assert (manifest_path.parent.parent / ".mcp.json").exists()
    assert (manifest_path.parent.parent / "hooks/hooks.json").exists()


def test_claude_marketplace_points_to_plugin() -> None:
    marketplace = _read_json(ROOT / ".claude-plugin/marketplace.json")

    assert marketplace["name"] == "orca"
    [entry] = marketplace["plugins"]
    assert entry["name"] == "orca"
    assert entry["source"] == "./plugin/orca"
    assert "codex" in entry["keywords"]
    assert (ROOT / entry["source"]).exists()


def test_codex_plugin_manifest_paths_exist() -> None:
    manifest_path = ROOT / "plugins/orca/.codex-plugin/plugin.json"
    manifest = _read_json(manifest_path)
    plugin_root = manifest_path.parent.parent

    assert manifest["name"] == "orca"
    assert manifest["skills"] == "./skills/"
    assert manifest["hooks"] == "./hooks.json"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert (plugin_root / "skills/orca-setup/SKILL.md").exists()
    assert (plugin_root / ".mcp.json").exists()
    assert (plugin_root / "hooks.json").exists()


def test_codex_marketplace_points_to_plugin() -> None:
    marketplace = _read_json(ROOT / ".agents/plugins/marketplace.json")

    assert marketplace["name"] == "orca"
    [entry] = marketplace["plugins"]
    assert entry["name"] == "orca"
    assert entry["source"] == {"source": "local", "path": "./plugins/orca"}
    assert entry["policy"] == {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_INSTALL"}
    assert (ROOT / entry["source"]["path"]).exists()


def test_codex_setup_skill_defaults_to_codex_worker() -> None:
    setup_skill = (ROOT / "plugins/orca/skills/orca-setup/SKILL.md").read_text()

    assert "kind: codex" in setup_skill
    assert "kind: claude-code" not in setup_skill
    assert "/mcp" not in setup_skill
