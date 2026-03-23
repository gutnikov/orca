from __future__ import annotations

import json
from pathlib import Path


class BranchMap:
    def __init__(self, repo_root: Path, branch_name: str) -> None:
        self.path = repo_root / ".orca" / "runs" / branch_name / "branches.json"
        self._map: dict[str, str] = {}

    def set(self, issue_id: str, branch: str) -> None:
        self._map[issue_id] = branch

    def get(self, issue_id: str) -> str | None:
        return self._map.get(issue_id)

    def values(self) -> list[str]:
        return list(self._map.values())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._map, indent=2))
        tmp.rename(self.path)

    def load(self) -> None:
        if self.path.exists():
            self._map = json.loads(self.path.read_text())
