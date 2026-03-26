from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SlackConfig:
    bot_token: str
    app_token: str


@dataclass(frozen=True)
class IntegrationsConfig:
    slack: SlackConfig | None = None


def _resolve_token(data: dict[str, Any], key: str, env_key: str) -> str:
    """Resolve a token from a literal value or environment variable."""
    literal = data.get(key)
    if literal is not None:
        return str(literal)
    env_var = data.get(env_key)
    if env_var is not None:
        value = os.environ.get(str(env_var))
        if value is None:
            msg = f"Environment variable '{env_var}' (from {env_key}) is not set"
            raise ValueError(msg)
        return value
    msg = f"Either '{key}' or '{env_key}' must be provided"
    raise ValueError(msg)


@dataclass(frozen=True)
class OrchestratorConfig:
    base_branch: str = "origin/main"


def parse_orchestrator_config(raw: dict[str, Any] | None) -> OrchestratorConfig:
    """Parse orchestrator-level config from orca.yml (fields outside the engine config)."""
    if not raw:
        return OrchestratorConfig()
    base_branch = raw.get("base_branch", "origin/main")
    return OrchestratorConfig(base_branch=str(base_branch))


def parse_integrations(raw: dict[str, Any] | None) -> IntegrationsConfig:
    """Parse the integrations section of orca.yml."""
    if not raw:
        return IntegrationsConfig()

    slack_data = raw.get("slack")
    slack: SlackConfig | None = None
    if slack_data is not None:
        bot_token = _resolve_token(slack_data, "bot_token", "bot_token_env")
        app_token = _resolve_token(slack_data, "app_token", "app_token_env")
        slack = SlackConfig(bot_token=bot_token, app_token=app_token)

    return IntegrationsConfig(slack=slack)
