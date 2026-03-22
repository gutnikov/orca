from __future__ import annotations

from pathlib import Path

from orca.orchestrator.branches import BranchMap


class TestBranchMap:
    def test_set_and_get(self, tmp_path: Path) -> None:
        branch_map = BranchMap(tmp_path, "main")
        branch_map.set("issue-1", "my-feature")
        assert branch_map.get("issue-1") == "my-feature"

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        branch_map = BranchMap(tmp_path, "main")
        assert branch_map.get("unknown-id") is None

    def test_persistence_round_trip(self, tmp_path: Path) -> None:
        # Create and populate first instance
        branch_map1 = BranchMap(tmp_path, "main")
        branch_map1.set("issue-1", "my-feature")
        branch_map1.set("issue-2", "another-feature")
        branch_map1.save()

        # Create new instance and load
        branch_map2 = BranchMap(tmp_path, "main")
        branch_map2.load()

        # Verify both entries persisted
        assert branch_map2.get("issue-1") == "my-feature"
        assert branch_map2.get("issue-2") == "another-feature"

    def test_load_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        branch_map = BranchMap(tmp_path, "main")
        branch_map.load()  # Should not raise
        assert branch_map.get("any-id") is None

    def test_file_path(self, tmp_path: Path) -> None:
        branch_map = BranchMap(tmp_path, "my-branch")
        expected_path = tmp_path / ".orca" / "runs" / "my-branch" / "branches.json"
        assert branch_map.path == expected_path
