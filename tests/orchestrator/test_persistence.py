from pathlib import Path

from orca.engine.types import State
from orca.orchestrator.persistence import Persistence


class TestPersistence:
    def test_save_and_load(self, tmp_path: Path) -> None:
        """Create empty State, save it, load it back, assert to_dict() matches."""
        persistence = Persistence(tmp_path, "main")
        state = State(issues={}, worker_queues={})

        persistence.save(state)
        loaded = persistence.load()

        assert loaded is not None
        assert loaded.to_dict() == state.to_dict()

    def test_load_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Load from nonexistent path returns None."""
        persistence = Persistence(tmp_path, "main")

        result = persistence.load()

        assert result is None

    def test_exists(self, tmp_path: Path) -> None:
        """False before save, true after."""
        persistence = Persistence(tmp_path, "main")

        assert not persistence.exists()

        state = State(issues={}, worker_queues={})
        persistence.save(state)

        assert persistence.exists()

    def test_state_path_uses_branch_name(self, tmp_path: Path) -> None:
        """Assert path is {root}/.orca/runs/{branch}/{workflow}/state.json."""
        persistence = Persistence(tmp_path, "feature/test", "prd")

        expected_path = tmp_path / ".orca" / "runs" / "feature/test" / "prd" / "state.json"
        assert persistence.state_path == expected_path

    def test_atomic_write(self, tmp_path: Path) -> None:
        """No .tmp file left after save, state file exists."""
        persistence = Persistence(tmp_path, "main")
        state = State(issues={}, worker_queues={})

        persistence.save(state)

        assert persistence.state_path.exists()
        tmp_file = persistence.state_path.with_suffix(".tmp")
        assert not tmp_file.exists()
