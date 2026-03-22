from __future__ import annotations

import pytest

from orca.engine.config import ConfigValidationError, parse_config
from orca.engine.types import (
    EnumFieldDef,
    ListFieldDef,
    OnDecompose,
    OnTransition,
    StringFieldDef,
)


class TestParseSimpleConfig:
    def test_states_exist(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert set(cfg.states.keys()) == {"todo", "implementing", "done"}

    def test_initial_state(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.initial == "todo"

    def test_terminal_state(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.states["done"].terminal is True
        assert cfg.states["done"].worker is None
        assert cfg.states["done"].on == {}

    def test_active_state_worker(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        state = cfg.states["todo"]
        assert state.worker is not None
        assert "outcome" in state.worker.result_format
        outcome = state.worker.result_format["outcome"]
        assert isinstance(outcome, EnumFieldDef)
        assert outcome.values == ["start"]

    def test_on_rules(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.states["todo"].on == {"start": OnTransition(target="implementing")}
        assert cfg.states["implementing"].on == {
            "complete": OnTransition(target="done"),
            "reject": OnTransition(target="todo"),
        }

    def test_string_result_format_field(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        rf = cfg.states["implementing"].worker
        assert rf is not None
        reason = rf.result_format["reason"]
        assert isinstance(reason, StringFieldDef)
        assert reason.description == "Explanation"

    def test_required_when_normalization(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        rf = cfg.states["implementing"].worker
        assert rf is not None
        reason = rf.result_format["reason"]
        assert isinstance(reason, StringFieldDef)
        assert reason.required_when == ["reject"]


class TestParseDecomposeConfig:
    def test_on_decompose_rule(self, decompose_config_yaml: str) -> None:
        cfg = parse_config(decompose_config_yaml)
        assert isinstance(cfg.states["scoping"].on["decompose"], OnDecompose)

    def test_on_transition_rule(self, decompose_config_yaml: str) -> None:
        cfg = parse_config(decompose_config_yaml)
        assert cfg.states["scoping"].on["implement"] == OnTransition(target="implementing")

    def test_list_field_def_with_issue_items(self, decompose_config_yaml: str) -> None:
        cfg = parse_config(decompose_config_yaml)
        worker = cfg.states["scoping"].worker
        assert worker is not None
        sub = worker.result_format["sub_issues"]
        assert isinstance(sub, ListFieldDef)
        assert sub.items == "$issue"
        assert sub.required_when == ["decompose"]


class TestParseMaxWorkersConfig:
    def test_max_workers(self, max_workers_config_yaml: str) -> None:
        cfg = parse_config(max_workers_config_yaml)
        assert cfg.states["apply"].max_workers == 1

    def test_no_max_workers_default(self, max_workers_config_yaml: str) -> None:
        cfg = parse_config(max_workers_config_yaml)
        assert cfg.states["todo"].max_workers is None


class TestParseIssueFields:
    def test_issue_fields(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert "title" in cfg.issue_fields
        assert cfg.issue_fields["title"].type == "string"
        assert cfg.issue_fields["title"].description == "Issue title"
        assert "priority" in cfg.issue_fields
        assert cfg.issue_fields["priority"].type == "enum"


class TestValidationErrors:
    def test_initial_references_existing_state(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    terminal: true
initial: nonexistent
"""
        with pytest.raises(ConfigValidationError, match="initial.*nonexistent"):
            parse_config(yaml_str)

    def test_on_target_references_existing_state(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values: [start]
          description: d
    on:
      start: ghost
  done:
    terminal: true
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="ghost"):
            parse_config(yaml_str)

    def test_on_key_matches_outcome_values(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values: [start]
          description: d
    on:
      bogus: done
  done:
    terminal: true
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="bogus"):
            parse_config(yaml_str)

    def test_active_state_requires_outcome_enum(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      result_format:
        reason:
          type: string
          description: d
    on:
      x: done
  done:
    terminal: true
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="outcome"):
            parse_config(yaml_str)

    def test_terminal_state_no_worker_or_on(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  done:
    terminal: true
    worker:
      result_format:
        outcome:
          type: enum
          values: [x]
          description: d
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="[Tt]erminal"):
            parse_config(yaml_str)

    def test_at_least_one_terminal_state(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: todo
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="[Tt]erminal"):
            parse_config(yaml_str)

    def test_decompose_requires_sub_issues_field(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values: [decompose]
          description: d
    on:
      decompose:
        action: decompose
  done:
    terminal: true
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="sub_issues"):
            parse_config(yaml_str)

    def test_unreachable_state(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  orphan:
    worker:
      result_format:
        outcome:
          type: enum
          values: [x]
          description: d
    on:
      x: done
  done:
    terminal: true
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="orphan"):
            parse_config(yaml_str)

    def test_max_workers_must_be_positive_integer(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    max_workers: 0
    worker:
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  done:
    terminal: true
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="max_workers"):
            parse_config(yaml_str)

    def test_max_workers_negative(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    max_workers: -1
    worker:
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  done:
    terminal: true
initial: todo
"""
        with pytest.raises(ConfigValidationError, match="max_workers"):
            parse_config(yaml_str)
