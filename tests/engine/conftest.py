from __future__ import annotations

from collections.abc import Callable

import pytest


def _clock(value: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: value


@pytest.fixture()
def simple_config_yaml() -> str:
    return """\
issue:
  fields:
    title:
      type: string
      description: Issue title
    priority:
      type: enum
      description: Priority level

states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values:
            - start
          description: Decision to start work
    on:
      start: implementing

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values:
            - complete
            - reject
          description: Implementation outcome
        reason:
          type: string
          description: Explanation
          required_when: reject
    on:
      complete: done
      reject: todo

  done:
    terminal: true

initial: todo
"""


@pytest.fixture()
def decompose_config_yaml() -> str:
    return """\
issue:
  fields:
    title:
      type: string
      description: Issue title

states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values:
            - scope
          description: Decision
    on:
      scope: scoping

  scoping:
    worker:
      result_format:
        outcome:
          type: enum
          values:
            - decompose
            - implement
          description: Scoping decision
        sub_issues:
          type: list
          items: "$issue"
          description: Sub-issues to create
          required_when:
            - decompose
    on:
      decompose:
        action: decompose
      implement: implementing

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values:
            - complete
          description: Implementation outcome
    on:
      complete: done

  done:
    terminal: true

initial: todo
"""


@pytest.fixture()
def max_workers_config_yaml() -> str:
    return """\
issue:
  fields:
    title:
      type: string
      description: Issue title

states:
  todo:
    worker:
      result_format:
        outcome:
          type: enum
          values:
            - start
          description: Decision
    on:
      start: implementing

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values:
            - ready
          description: Outcome
    on:
      ready: apply

  apply:
    max_workers: 1
    worker:
      result_format:
        outcome:
          type: enum
          values:
            - applied
          description: Apply result
    on:
      applied: done

  done:
    terminal: true

initial: todo
"""
