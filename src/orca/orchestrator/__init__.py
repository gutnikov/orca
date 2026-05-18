"""Orca orchestrator — runs workers and manages the engine event loop."""

from orca.orchestrator.branches import BranchMap
from orca.orchestrator.log import JSONFormatter, setup_logging
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.runner import main, parse_task_file, run
from orca.orchestrator.session_sync import SessionManifest, SessionSync
from orca.orchestrator.template import render_prompt, render_prompt_string
from orca.orchestrator.validation import validate_result
from orca.orchestrator.worker import (
    KIND_REGISTRY,
    CliAgentWorker,
    KindConfig,
    Worker,
    WorkerFailure,
    WorkerOutcome,
    WorkerSuccess,
)
from orca.orchestrator.worktree import WorktreeManager

__all__ = [
    "BranchMap",
    "CliAgentWorker",
    "JSONFormatter",
    "KIND_REGISTRY",
    "KindConfig",
    "Orchestrator",
    "Persistence",
    "SessionManifest",
    "SessionSync",
    "Worker",
    "WorkerFailure",
    "WorkerOutcome",
    "WorkerSuccess",
    "WorktreeManager",
    "main",
    "parse_task_file",
    "render_prompt",
    "render_prompt_string",
    "run",
    "setup_logging",
    "validate_result",
]
