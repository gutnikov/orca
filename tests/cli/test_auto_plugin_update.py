"""Tests for the plugin auto-update helper triggered on `orca daemon start`."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from orca.cli.daemon_cmd import _auto_update_agent_plugins


def test_skipped_when_env_var_set() -> None:
    """ORCA_NO_AUTO_UPDATE=1 disables the auto-update entirely."""
    with patch.dict(os.environ, {"ORCA_NO_AUTO_UPDATE": "1"}), patch("shutil.which") as which_mock:
        _auto_update_agent_plugins()
        # Nothing should call shutil.which when opted out
        which_mock.assert_not_called()


def test_skipped_when_no_agent_cli_on_path() -> None:
    """No claude / codex on PATH → nothing runs. Should not raise."""
    os.environ.pop("ORCA_NO_AUTO_UPDATE", None)
    with (
        patch("shutil.which", return_value=None) as which_mock,
        patch("subprocess.run") as run_mock,
    ):
        _auto_update_agent_plugins()
        # Give the daemon threads a moment to run
        import time

        time.sleep(0.1)
        assert which_mock.called  # we checked PATH
        run_mock.assert_not_called()  # but never invoked plugin update


def test_runs_in_background_does_not_block() -> None:
    """The helper returns immediately; updates run in detached threads.

    We don't actually want to invoke claude here, so we patch shutil.which to
    return None (no CLI installed) — proving the helper exits cleanly even
    in CI environments with no agent CLI.
    """
    os.environ.pop("ORCA_NO_AUTO_UPDATE", None)
    with patch("shutil.which", return_value=None):
        # If this took >1s we'd know it's blocking
        import time

        t0 = time.time()
        _auto_update_agent_plugins()
        elapsed = time.time() - t0
        assert elapsed < 1.0, f"helper blocked for {elapsed:.2f}s"


def test_invokes_subprocess_when_cli_found() -> None:
    """If claude is on PATH, the update subprocess is launched."""
    os.environ.pop("ORCA_NO_AUTO_UPDATE", None)

    def fake_which(cli: str) -> str | None:
        return "/usr/local/bin/claude" if cli == "claude" else None

    call_args: list[list[str]] = []

    def fake_run(args, **kwargs):  # noqa: ANN001
        call_args.append(args)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with (
        patch("shutil.which", side_effect=fake_which),
        patch("subprocess.run", side_effect=fake_run),
    ):
        _auto_update_agent_plugins()
        # Let the background thread run
        import time

        time.sleep(0.3)

    # claude got invoked; codex didn't (not on PATH)
    invocations = [args for args in call_args if args[0] == "claude"]
    assert any("plugin" in args and "update" in args for args in invocations), (
        f"expected claude plugin update call, got: {call_args}"
    )
    assert all(args[0] != "codex" for args in call_args), "codex shouldn't have been invoked"
