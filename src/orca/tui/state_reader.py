from __future__ import annotations

import json
from pathlib import Path

from orca.engine.types import State


class StateReader:
    """Reads orchestrator state from disk with mtime-based change detection."""

    def __init__(self, run_dir: Path) -> None:
        self._state_path = run_dir / "state.json"
        self._last_mtime: float = 0.0

    @property
    def last_mtime(self) -> float:
        return self._last_mtime

    def read(self) -> State | None:
        if not self._state_path.exists():
            return None
        mtime = self._state_path.stat().st_mtime
        if mtime == self._last_mtime:
            return None
        self._last_mtime = mtime
        data = json.loads(self._state_path.read_text())
        return State.from_dict(data)

    def reset(self) -> None:
        self._last_mtime = 0.0
