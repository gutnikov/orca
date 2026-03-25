from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import os
import struct
import subprocess
import termios
from pathlib import Path
from typing import IO

import pyte
import pyte.screens
from rich.text import Text

_DEFAULT_HISTORY = 10_000


class PtySession:
    """Pty-backed subprocess with in-memory VT100 terminal emulator."""

    def __init__(self, cols: int = 120, rows: int = 40) -> None:
        self._cols = cols
        self._rows = rows
        self._stream = pyte.Stream()
        self.screen: pyte.HistoryScreen = pyte.HistoryScreen(cols, rows, history=_DEFAULT_HISTORY)
        self._stream.attach(self.screen)
        self._master_fd: int | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_file: IO[bytes] | None = None

    @property
    def alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    @property
    def pid(self) -> int:
        if self._proc is None:
            raise RuntimeError("PtySession not spawned")
        return self._proc.pid

    async def spawn(
        self,
        cmd: str,
        args: list[str],
        cwd: str | Path,
        env: dict[str, str] | None = None,
        log_path: Path | None = None,
        stdin_data: bytes | None = None,
    ) -> None:
        """Spawn a process in a pty.

        All three standard fds (stdin/stdout/stderr) are connected to the pty
        slave so the child sees a real tty.  When *stdin_data* is provided it
        is written to the master fd with echo disabled so the prompt reaches
        the child without polluting the terminal output.
        """
        master_fd, slave_fd = os.openpty()

        winsize = struct.pack("HHHH", self._rows, self._cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        # Disable echo on the pty BEFORE spawning so prompt writes don't
        # get reflected back to the master fd.
        if stdin_data is not None:
            attrs = termios.tcgetattr(slave_fd)
            attrs[3] &= ~termios.ECHO  # lflags
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        spawn_env = os.environ.copy()
        spawn_env["TERM"] = "xterm-256color"
        if env:
            spawn_env.update(env)

        self._proc = subprocess.Popen(
            [cmd, *args],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(cwd),
            env=spawn_env,
            close_fds=True,
            start_new_session=True,
        )

        os.close(slave_fd)
        self._master_fd = master_fd

        # Write prompt to master fd — it arrives on the child's stdin.
        # Echo is disabled so the prompt bytes won't be reflected back.
        if stdin_data is not None:
            os.write(master_fd, stdin_data)

        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(log_path, "wb")  # noqa: SIM115

    async def read_loop(self) -> None:
        if self._master_fd is None:
            raise RuntimeError("PtySession not spawned")

        loop = asyncio.get_running_loop()
        fd = self._master_fd
        event = asyncio.Event()

        def _on_readable() -> None:
            event.set()

        loop.add_reader(fd, _on_readable)
        try:
            while True:
                await event.wait()
                event.clear()
                try:
                    data = os.read(fd, 65536)
                except OSError as e:
                    if e.errno == errno.EIO:
                        break
                    if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        continue
                    raise
                if not data:
                    break
                if self._log_file is not None:
                    self._log_file.write(data)
                self._stream.feed(data.decode("utf-8", errors="replace"))
        finally:
            loop.remove_reader(fd)
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None

    def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal to *cols* x *rows*."""
        self._cols = cols
        self._rows = rows
        self.screen.resize(rows, cols)
        if self._master_fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    @staticmethod
    def pyte_line_to_rich(row_data: dict[int, pyte.screens.Char], cols: int) -> Text:
        """Convert a pyte row (dict of column -> Char) to a Rich Text."""
        text = Text()
        for col in range(cols):
            char = row_data.get(col, pyte.screens.Char(" "))
            style_parts: list[str] = []
            if char.fg and char.fg != "default":
                style_parts.append(char.fg)
            if char.bg and char.bg != "default":
                style_parts.append(f"on {char.bg}")
            if char.bold:
                style_parts.append("bold")
            if char.italics:
                style_parts.append("italic")
            if char.underscore:
                style_parts.append("underline")
            style_str = " ".join(style_parts) if style_parts else ""
            text.append(char.data, style=style_str)
        return text

    def snapshot(self) -> list[Text]:
        """Return the full terminal state as a list of Rich Text lines."""
        lines: list[Text] = []
        # Scrollback history
        for row_data in self.screen.history.top:
            lines.append(self.pyte_line_to_rich(row_data, self._cols))
        # Current screen buffer
        for row in range(self.screen.lines):
            lines.append(self.pyte_line_to_rich(self.screen.buffer[row], self._cols))
        return lines

    def close(self) -> None:
        if self._master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            self._master_fd = None
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
