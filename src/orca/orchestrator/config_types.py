from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OrchestratorConfig:
    base_branch: str = "origin/main"


def parse_orchestrator_config(raw: dict[str, Any] | None) -> OrchestratorConfig:
    """Parse orchestrator-level config from orca.yml (fields outside the engine config)."""
    if not raw:
        return OrchestratorConfig()
    base_branch = raw.get("base_branch", "origin/main")
    return OrchestratorConfig(base_branch=str(base_branch))
