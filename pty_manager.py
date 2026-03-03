"""PTY Manager — spawns a bash shell in a pseudo-terminal with read/write/resize/close."""

import os
import select

from ptyprocess import PtyProcess


class PTYManager:
    """Manages a shell subprocess running in a pseudo-terminal.

    Provides non-blocking read, raw write, resize, and lifecycle control
    for the underlying PTY process.
    """

    def __init__(
        self,
        shell: str = "/bin/bash",
        cols: int = 120,
        rows: int = 40,
    ) -> None:
        self._shell = shell
        self._cols = cols
        self._rows = rows
        self._process: PtyProcess | None = None

    def spawn(self) -> None:
        """Spawn a new shell process in a pseudo-terminal.

        Sets TERM=xterm-256color so the shell and any programs it runs
        produce proper escape sequences for 256-color terminals.
        """
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        self._process = PtyProcess.spawn(
            [self._shell],
            dimensions=(self._rows, self._cols),
            env=env,
        )

    def read(self, timeout: float = 0.1) -> bytes:
        """Read all available data from the PTY, non-blocking.

        Uses select.select to wait up to *timeout* seconds for the first
        chunk, then drains any remaining data with a short poll.

        Returns b"" if no data is available or the process is not running.
        """
        if self._process is None:
            return b""

        fd = self._process.fd
        readable, _, _ = select.select([fd], [], [], timeout)
        if not readable:
            return b""

        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(fd, 4096)
                if chunk:
                    chunks.append(chunk)
                else:
                    break
            except OSError:
                break

            # Check if more data is immediately available.
            ready, _, _ = select.select([fd], [], [], 0.01)
            if not ready:
                break

        return b"".join(chunks)

    def write(self, data: bytes) -> None:
        """Write raw bytes to the PTY.

        No-op if the process has not been spawned or has been closed.
        """
        if self._process is None:
            return
        self._process.write(data)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY to the given dimensions.

        No-op if the process is not running.
        """
        if self._process is None:
            return
        self._process.setwinsize(rows, cols)

    def is_alive(self) -> bool:
        """Return True if the shell process is still running."""
        if self._process is None:
            return False
        return self._process.isalive()

    def close(self) -> None:
        """Terminate the shell process and release resources.

        Force-kills the process and sets the internal reference to None.
        Safe to call when the process is already closed or was never spawned.
        """
        if self._process is None:
            return
        try:
            self._process.terminate(force=True)
        except Exception:
            pass
        self._process = None
