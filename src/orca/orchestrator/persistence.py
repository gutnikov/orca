from __future__ import annotations

import json
from pathlib import Path

from orca.engine.types import State


class Persistence:
    def __init__(self, repo_root: Path, branch_name: str) -> None:
        self.state_path = repo_root / ".orca" / "runs" / branch_name / "state.json"

    def save(self, state: State) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2))
        tmp.rename(self.state_path)

    def load(self) -> State | None:
        if not self.state_path.exists():
            return None
        return State.from_dict(json.loads(self.state_path.read_text()))

    def exists(self) -> bool:
        return self.state_path.exists()
