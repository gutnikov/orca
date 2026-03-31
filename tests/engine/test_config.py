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
        assert set(cfg.types["default"].states.keys()) == {"todo", "implementing", "done"}

    def test_initial_state(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.types["default"].initial == "todo"

    def test_terminal_state(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.types["default"].states["done"].terminal is True
        assert cfg.types["default"].states["done"].worker is None
        assert cfg.types["default"].states["done"].on == {}

    def test_active_state_worker(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        state = cfg.types["default"].states["todo"]
        assert state.worker is not None
        assert "outcome" in state.worker.result_format
        outcome = state.worker.result_format["outcome"]
        assert isinstance(outcome, EnumFieldDef)
        assert outcome.values == ["start"]

    def test_on_rules(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.types["default"].states["todo"].on == {"start": OnTransition(target="implementing")}
        assert cfg.types["default"].states["implementing"].on == {
            "complete": OnTransition(target="done"),
            "reject": OnTransition(target="todo"),
        }

    def test_string_result_format_field(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        rf = cfg.types["default"].states["implementing"].worker
        assert rf is not None
        reason = rf.result_format["reason"]
        assert isinstance(reason, StringFieldDef)
        assert reason.description == "Explanation"

    def test_required_when_normalization(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        rf = cfg.types["default"].states["implementing"].worker
        assert rf is not None
        reason = rf.result_format["reason"]
        assert isinstance(reason, StringFieldDef)
        assert reason.required_when == ["reject"]

    def test_root_type_is_default(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        assert cfg.root_type == "default"


class TestParseDecomposeConfig:
    def test_on_decompose_rule(self, decompose_config_yaml: str) -> None:
        cfg = parse_config(decompose_config_yaml)
        assert isinstance(cfg.types["default"].states["scoping"].on["decompose"], OnDecompose)

    def test_on_transition_rule(self, decompose_config_yaml: str) -> None:
        cfg = parse_config(decompose_config_yaml)
        assert cfg.types["default"].states["scoping"].on["implement"] == OnTransition(target="implementing")

    def test_list_field_def_with_issue_items(self, decompose_config_yaml: str) -> None:
        cfg = parse_config(decompose_config_yaml)
        worker = cfg.types["default"].states["scoping"].worker
        assert worker is not None
        sub = worker.result_format["sub_issues"]
        assert isinstance(sub, ListFieldDef)
        assert sub.items == "$issue"
        assert sub.required_when == ["decompose"]


class TestParseMaxWorkersConfig:
    def test_max_workers(self, max_workers_config_yaml: str) -> None:
        cfg = parse_config(max_workers_config_yaml)
        assert cfg.types["default"].states["apply"].max_workers == 1

    def test_no_max_workers_default(self, max_workers_config_yaml: str) -> None:
        cfg = parse_config(max_workers_config_yaml)
        assert cfg.types["default"].states["todo"].max_workers is None


class TestParseIssueFields:
    def test_issue_fields(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        fields = cfg.types["default"].fields
        assert "title" in fields
        assert fields["title"].type == "string"
        assert fields["title"].description == "Issue title"
        assert "priority" in fields
        assert fields["priority"].type == "enum"


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
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  orphan:
    worker:
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
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
      kind: claude-code
      prompt: prompts/default.md
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

    def test_max_hops_ignored_from_yaml(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/default.md
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
max_hops: 0
"""
        cfg = parse_config(yaml_str)
        assert cfg.max_hops is None  # max_hops from YAML is ignored


class TestParseMaxHops:
    def test_max_hops_not_parsed_from_yaml(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/default.md
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
max_hops: 50
"""
        cfg = parse_config(yaml_str)
        assert cfg.max_hops is None  # max_hops is CLI-only now


class TestWorkerDefFields:
    def test_parse_worker_with_kind_and_prompt(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
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
        cfg = parse_config(yaml_str)
        worker = cfg.types["default"].states["todo"].worker
        assert worker is not None
        assert worker.kind == "claude-code"
        assert worker.prompt == "prompts/work.md"
        assert worker.timeout is None

    def test_parse_worker_with_timeout(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
      timeout: 300
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
        cfg = parse_config(yaml_str)
        worker = cfg.types["default"].states["todo"].worker
        assert worker is not None
        assert worker.timeout == 300

    def test_invalid_kind_rejected(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: unknown-worker
      prompt: prompts/work.md
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
        with pytest.raises(ConfigValidationError, match="kind must be one of"):
            parse_config(yaml_str)

    def test_missing_prompt_rejected(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
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
        with pytest.raises(ConfigValidationError, match="prompt"):
            parse_config(yaml_str)

    def test_invalid_timeout_rejected(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
      timeout: -1
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
        with pytest.raises(ConfigValidationError, match="timeout"):
            parse_config(yaml_str)

    def test_parse_worker_with_model(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
      model: anthropic/claude-sonnet-4-5
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
        cfg = parse_config(yaml_str)
        worker = cfg.types["default"].states["todo"].worker
        assert worker is not None
        assert worker.model == "anthropic/claude-sonnet-4-5"

    def test_parse_worker_with_args(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
      args: ["--max-turns", "100"]
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
        cfg = parse_config(yaml_str)
        worker = cfg.types["default"].states["todo"].worker
        assert worker is not None
        assert worker.args == ("--max-turns", "100")

    def test_parse_worker_model_and_args_default_none(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
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
        cfg = parse_config(yaml_str)
        worker = cfg.types["default"].states["todo"].worker
        assert worker is not None
        assert worker.model is None
        assert worker.args is None

    def test_opencode_kind_accepted(self) -> None:
        yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: opencode
      prompt: prompts/work.md
      model: anthropic/claude-sonnet-4-5
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
        cfg = parse_config(yaml_str)
        worker = cfg.types["default"].states["todo"].worker
        assert worker is not None
        assert worker.kind == "opencode"


class TestParseTypedConfig:
    TYPED_YAML = """\
root_type: epic
max_hops: 15
types:
  epic:
    fields:
      title: {type: string, description: "Title"}
      scope: {type: string, description: "Scope"}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scope.md
          result_format:
            outcome:
              type: enum
              values: [ready, decompose]
              description: d
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
              description: s
        on:
          ready: done
          decompose:
            action: decompose
            child_type: task
            then: done
      done:
        terminal: true
  task:
    fields:
      title: {type: string, description: "Title"}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/impl.md
          result_format:
            outcome:
              type: enum
              values: [done]
              description: d
        on:
          done: done
      done:
        terminal: true
"""

    def test_root_type(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert cfg.root_type == "epic"

    def test_types_parsed(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert set(cfg.types.keys()) == {"epic", "task"}

    def test_epic_fields(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert "title" in cfg.types["epic"].fields
        assert "scope" in cfg.types["epic"].fields

    def test_task_initial(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert cfg.types["task"].initial == "implementing"

    def test_decompose_child_type(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        rule = cfg.types["epic"].states["scoping"].on["decompose"]
        assert isinstance(rule, OnDecompose)
        assert rule.child_type == "task"

    def test_max_hops_not_parsed(self) -> None:
        cfg = parse_config(self.TYPED_YAML)
        assert cfg.max_hops is None  # max_hops is CLI-only, not parsed from YAML


class TestTypedConfigValidation:
    def test_root_type_must_exist(self) -> None:
        yaml_str = """\
root_type: ghost
types:
  epic:
    fields: {}
    initial: done
    states:
      done: {terminal: true}
"""
        with pytest.raises(ConfigValidationError, match="root_type.*ghost"):
            parse_config(yaml_str)

    def test_child_type_must_exist(self) -> None:
        yaml_str = """\
root_type: epic
types:
  epic:
    fields: {}
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: p.md
          result_format:
            outcome: {type: enum, values: [decompose], description: d}
            sub_issues: {type: list, items: "$issue", required_when: [decompose], description: s}
        on:
          decompose:
            action: decompose
            child_type: ghost
      done: {terminal: true}
"""
        with pytest.raises(ConfigValidationError, match="child_type.*ghost"):
            parse_config(yaml_str)

    def test_cross_type_transition_rejected(self) -> None:
        yaml_str = """\
root_type: epic
types:
  epic:
    fields: {}
    initial: todo
    states:
      todo:
        worker:
          kind: claude-code
          prompt: p.md
          result_format:
            outcome: {type: enum, values: [go], description: d}
        on:
          go: implementing
      done: {terminal: true}
  task:
    fields: {}
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: p.md
          result_format:
            outcome: {type: enum, values: [done], description: d}
        on:
          done: done
      done: {terminal: true}
"""
        with pytest.raises(ConfigValidationError, match="implementing.*does not exist"):
            parse_config(yaml_str)


class TestNeedsFeedbackValidation:
    """needs_feedback in outcome values should not require a matching on: rule."""

    def test_needs_feedback_outcome_without_on_rule_is_valid(self) -> None:
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: Issue title

states:
  working:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - done
            - needs_feedback
          description: Outcome
        feedback_questions:
          type: string
          description: Questions for user
          required_when: needs_feedback
    on:
      done: finished

  finished:
    terminal: true

initial: working
"""
        config = parse_config(yaml_str)
        outcome = config.types["default"].states["working"].worker
        assert outcome is not None
        assert "needs_feedback" in outcome.result_format["outcome"].values  # type: ignore[union-attr]

    def test_needs_feedback_only_outcome_is_invalid(self) -> None:
        """A state with ONLY needs_feedback and no real on: rules is invalid (no way to progress)."""
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: Issue title

states:
  working:
    worker:
      kind: claude-code
      prompt: prompts/default.md
      result_format:
        outcome:
          type: enum
          values:
            - needs_feedback
          description: Outcome
        feedback_questions:
          type: string
          description: Questions
          required_when: needs_feedback
    on: {}

  done:
    terminal: true

initial: working
"""
        with pytest.raises(ConfigValidationError):
            parse_config(yaml_str)
