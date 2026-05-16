"""Smoke test for the bundled example workflow at examples/project/orca.yml.

The example is referenced from the playbooks as the canonical worked example.
If the config schema evolves without updating the example, agents reading the
playbooks will copy a config shape that no longer validates. This test catches
that drift on every CI run.
"""

from __future__ import annotations

import pathlib

import pytest

from orca.engine.config import parse_config

EXAMPLE_PATH = pathlib.Path(__file__).resolve().parents[2] / "examples" / "project" / "orca.yml"


@pytest.mark.skipif(not EXAMPLE_PATH.exists(), reason="examples/project/orca.yml not present")
def test_example_workflow_parses() -> None:
    config = parse_config(EXAMPLE_PATH.read_text())
    # The example is a single-type config (auto-wrapped as 'default').
    assert "default" in config.types
    type_def = config.types["default"]
    # Spot-check: every state's on: targets resolve, every active state has a worker.
    for state_name, state in type_def.states.items():
        if state.worker is not None:
            assert state.worker.prompt, f"{state_name}: worker.prompt is empty"
        for outcome in state.on:
            assert outcome, f"{state_name}: empty outcome key in on:"


@pytest.mark.skipif(not EXAMPLE_PATH.exists(), reason="examples/project/orca.yml not present")
def test_example_workflow_prompts_referenced_exist() -> None:
    config = parse_config(EXAMPLE_PATH.read_text())
    example_dir = EXAMPLE_PATH.parent
    for type_def in config.types.values():
        for state_name, state in type_def.states.items():
            if state.worker is None:
                continue
            prompt_path = example_dir / state.worker.prompt
            assert prompt_path.exists(), f"{state_name}: prompt missing at {prompt_path}"
