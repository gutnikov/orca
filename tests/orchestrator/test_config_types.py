from __future__ import annotations

import pytest

from orca.orchestrator.config_types import parse_integrations


class TestParseIntegrations:
    def test_literal_tokens(self) -> None:
        raw = {"slack": {"bot_token": "xoxb-123", "app_token": "xapp-456"}}
        result = parse_integrations(raw)
        assert result.slack is not None
        assert result.slack.bot_token == "xoxb-123"
        assert result.slack.app_token == "xapp-456"

    def test_env_var_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_BOT_TOKEN", "xoxb-from-env")
        monkeypatch.setenv("MY_APP_TOKEN", "xapp-from-env")
        raw = {"slack": {"bot_token_env": "MY_BOT_TOKEN", "app_token_env": "MY_APP_TOKEN"}}
        result = parse_integrations(raw)
        assert result.slack is not None
        assert result.slack.bot_token == "xoxb-from-env"
        assert result.slack.app_token == "xapp-from-env"

    def test_missing_env_var_raises(self) -> None:
        raw = {"slack": {"bot_token_env": "NONEXISTENT_VAR", "app_token_env": "ALSO_MISSING"}}
        with pytest.raises(ValueError, match="NONEXISTENT_VAR"):
            parse_integrations(raw)

    def test_no_slack_section(self) -> None:
        result = parse_integrations({})
        assert result.slack is None

    def test_none_input(self) -> None:
        result = parse_integrations(None)
        assert result.slack is None
