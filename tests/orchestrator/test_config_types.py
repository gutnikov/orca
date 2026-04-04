from __future__ import annotations

from orca.orchestrator.config_types import parse_orchestrator_config


class TestParseOrchestratorConfig:
    def test_base_branch_from_config(self) -> None:
        raw = {"base_branch": "origin/develop"}
        result = parse_orchestrator_config(raw)
        assert result.base_branch == "origin/develop"

    def test_base_branch_default(self) -> None:
        result = parse_orchestrator_config({})
        assert result.base_branch == "origin/main"

    def test_base_branch_none_input(self) -> None:
        result = parse_orchestrator_config(None)
        assert result.base_branch == "origin/main"
