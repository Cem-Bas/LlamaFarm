"""Virtual terminal screen buffer using pyte.

Wraps pyte's Screen and Stream classes to maintain a virtual terminal
that the agent reads PTY output into and extracts current screen text from.
"""

import pyte


class TerminalScreen:
    """A virtual terminal screen buffer backed by pyte.

    Feeds raw PTY output bytes into a pyte Stream/Screen pair and
    provides the current screen content as stripped text lines.
    """

    def __init__(self, cols: int = 80, rows: int = 24) -> None:
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.Stream(self._screen)
        self._changed = False

    def feed(self, data: bytes) -> None:
        """Feed raw bytes into the terminal stream.

        Decodes bytes as UTF-8 with replacement for invalid sequences.
        Sets the changed flag only if data is non-empty.
        """
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        self._stream.feed(text)
        self._changed = True

    def get_text(self) -> str:
        """Return the current screen content as text.

        Each row becomes one line, with trailing whitespace stripped.
        Resets the changed flag.
        """
        lines = []
        for row in range(self._screen.lines):
            line = self._screen.display[row].rstrip()
            lines.append(line)
        self._changed = False
        return "\n".join(lines)

    def has_changed(self) -> bool:
        """Whether new data has been fed since the last get_text() call."""
        return self._changed

    def get_cursor_position(self) -> tuple[int, int]:
        """Return the current cursor position as (row, col)."""
        return (self._screen.cursor.y, self._screen.cursor.x)
