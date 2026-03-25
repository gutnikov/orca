from __future__ import annotations

import asyncio
import logging
import re
import shlex
import subprocess
from pathlib import Path

from rich.text import Text

# Pattern to strip ANSI background color sequences (48;5;N and 48;2;R;G;B)
# so that Textual's theme background shows through instead of Claude's.
_BG_COLOR_RE = re.compile(r"\x1b\[(?:48;5;\d+|48;2;\d+;\d+;\d+)m")

logger = logging.getLogger(__name__)

# Unique prefix for orca-managed tmux sessions
_TMUX_PREFIX = "orca-worker-"


class TmuxSession:
    """Manages a worker process inside a tmux session.

    Spawns the command in a detached tmux session and provides methods to
    capture the visible pane content (with ANSI colours) for TUI rendering.
    """

    def __init__(self, session_name: str, cols: int = 120, rows: int = 40) -> None:
        self._session_name = f"{_TMUX_PREFIX}{session_name}"
        self._cols = cols
        self._rows = rows
        self._alive = False

    @property
    def alive(self) -> bool:
        """Check if the tmux session still exists."""
        if not self._alive:
            return False
        result = subprocess.run(
            ["tmux", "has-session", "-t", self._session_name],
            capture_output=True,
        )
        self._alive = result.returncode == 0
        return self._alive

    @property
    def session_name(self) -> str:
        return self._session_name

    async def spawn(
        self,
        cmd: str,
        args: list[str],
        cwd: str | Path,
        env: dict[str, str] | None = None,
        stdin_data: bytes | None = None,
    ) -> None:
        """Spawn a process inside a new detached tmux session."""
        full_cmd = shlex.join([cmd, *args])

        # If we have stdin data, write it to a file and pipe it
        if stdin_data is not None:
            prompt_file = Path(str(cwd)) / ".orca" / ".prompt.tmp"
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            prompt_file.write_bytes(stdin_data)
            full_cmd = f"cat {shlex.quote(str(prompt_file))} | {full_cmd}"

        tmux_args = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            self._session_name,
            "-x",
            str(self._cols),
            "-y",
            str(self._rows),
            full_cmd,
        ]

        proc = await asyncio.create_subprocess_exec(
            *tmux_args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"Failed to create tmux session {self._session_name}")

        self._alive = True
        logger.debug("Tmux session %s started", self._session_name)

    def capture_pane(self) -> str:
        """Capture the current visible pane content with ANSI escape sequences."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self._session_name, "-p", "-e"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        return result.stdout

    def capture_scrollback(self) -> str:
        """Capture full scrollback history with ANSI escape sequences."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self._session_name, "-p", "-e", "-S", "-"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        return result.stdout

    def capture_rich(self) -> Text:
        """Capture pane content as a Rich Text object with ANSI styling."""
        raw = self.capture_pane()
        if not raw:
            return Text("")
        # Strip background colors so Textual's theme shows through
        raw = _BG_COLOR_RE.sub("", raw)
        return Text.from_ansi(raw)

    def snapshot(self) -> Text:
        """Capture full scrollback as a Rich Text object (for frozen display)."""
        raw = self.capture_scrollback()
        if not raw:
            return Text("")
        raw = _BG_COLOR_RE.sub("", raw)
        return Text.from_ansi(raw)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the tmux window."""
        self._cols = cols
        self._rows = rows
        subprocess.run(
            ["tmux", "resize-window", "-t", self._session_name, "-x", str(cols), "-y", str(rows)],
            capture_output=True,
        )

    async def wait(self, timeout: float | None = None) -> int:
        """Wait for the tmux session to end. Returns 0 on normal exit."""
        interval = 0.5
        elapsed = 0.0
        while self.alive:
            await asyncio.sleep(interval)
            elapsed += interval
            if timeout is not None and elapsed >= timeout:
                self.kill()
                return -1
        return 0

    def kill(self) -> None:
        """Kill the tmux session."""
        subprocess.run(
            ["tmux", "kill-session", "-t", self._session_name],
            capture_output=True,
        )
        self._alive = False

    def close(self) -> None:
        """Clean up the tmux session if it's still running."""
        if self.alive:
            self.kill()


# Keep PtySession as an alias for backward compatibility in imports
PtySession = TmuxSession
