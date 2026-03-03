"""Tests for TerminalScreen pyte wrapper."""

import pytest

from screen import TerminalScreen


class TestTerminalScreenInit:
    """Tests for TerminalScreen initialization."""

    def test_default_dimensions(self):
        ts = TerminalScreen()
        text = ts.get_text()
        lines = text.split("\n")
        assert len(lines) == 24

    def test_custom_dimensions(self):
        ts = TerminalScreen(cols=40, rows=10)
        text = ts.get_text()
        lines = text.split("\n")
        assert len(lines) == 10

    def test_initial_screen_is_blank(self):
        ts = TerminalScreen(cols=10, rows=3)
        text = ts.get_text()
        # All lines should be empty after stripping trailing whitespace
        for line in text.split("\n"):
            assert line == ""

    def test_initial_cursor_position(self):
        ts = TerminalScreen()
        row, col = ts.get_cursor_position()
        assert row == 0
        assert col == 0

    def test_initial_has_changed_is_false(self):
        ts = TerminalScreen()
        assert ts.has_changed() is False


class TestFeed:
    """Tests for feeding data into the screen."""

    def test_feed_simple_text(self):
        ts = TerminalScreen(cols=80, rows=24)
        ts.feed(b"Hello, World!")
        text = ts.get_text()
        lines = text.split("\n")
        assert lines[0] == "Hello, World!"

    def test_feed_sets_changed_flag(self):
        ts = TerminalScreen()
        ts.feed(b"data")
        assert ts.has_changed() is True

    def test_feed_empty_bytes_does_not_set_changed(self):
        ts = TerminalScreen()
        ts.feed(b"")
        assert ts.has_changed() is False

    def test_feed_multiple_times(self):
        ts = TerminalScreen(cols=80, rows=24)
        ts.feed(b"Hello")
        ts.feed(b", World!")
        text = ts.get_text()
        lines = text.split("\n")
        assert lines[0] == "Hello, World!"

    def test_feed_with_newline(self):
        ts = TerminalScreen(cols=80, rows=24)
        ts.feed(b"Line 1\r\nLine 2")
        text = ts.get_text()
        lines = text.split("\n")
        assert lines[0] == "Line 1"
        assert lines[1] == "Line 2"

    def test_feed_utf8_text(self):
        ts = TerminalScreen(cols=80, rows=24)
        ts.feed("Hello".encode("utf-8"))
        text = ts.get_text()
        assert "Hello" in text

    def test_feed_invalid_utf8_replaces_errors(self):
        ts = TerminalScreen(cols=80, rows=24)
        # Invalid UTF-8 sequence should not raise
        ts.feed(b"\xff\xfe")
        # Should not raise, replacement character handling
        text = ts.get_text()
        assert isinstance(text, str)


class TestGetText:
    """Tests for extracting text from the screen."""

    def test_get_text_returns_string(self):
        ts = TerminalScreen()
        text = ts.get_text()
        assert isinstance(text, str)

    def test_get_text_strips_trailing_whitespace(self):
        ts = TerminalScreen(cols=80, rows=5)
        ts.feed(b"Hello")
        text = ts.get_text()
        lines = text.split("\n")
        # First line has "Hello" with no trailing spaces
        assert lines[0] == "Hello"
        # Remaining lines should be empty (stripped)
        for line in lines[1:]:
            assert line == ""

    def test_get_text_resets_changed_flag(self):
        ts = TerminalScreen()
        ts.feed(b"data")
        assert ts.has_changed() is True
        ts.get_text()
        assert ts.has_changed() is False

    def test_get_text_correct_number_of_lines(self):
        ts = TerminalScreen(cols=40, rows=10)
        ts.feed(b"test")
        text = ts.get_text()
        lines = text.split("\n")
        assert len(lines) == 10

    def test_get_text_preserves_content_across_calls(self):
        ts = TerminalScreen(cols=80, rows=24)
        ts.feed(b"Persistent text")
        text1 = ts.get_text()
        text2 = ts.get_text()
        assert text1 == text2


class TestHasChanged:
    """Tests for the changed flag behavior."""

    def test_changed_false_initially(self):
        ts = TerminalScreen()
        assert ts.has_changed() is False

    def test_changed_true_after_feed(self):
        ts = TerminalScreen()
        ts.feed(b"something")
        assert ts.has_changed() is True

    def test_changed_false_after_get_text(self):
        ts = TerminalScreen()
        ts.feed(b"something")
        ts.get_text()
        assert ts.has_changed() is False

    def test_changed_true_again_after_new_feed(self):
        ts = TerminalScreen()
        ts.feed(b"first")
        ts.get_text()
        assert ts.has_changed() is False
        ts.feed(b"second")
        assert ts.has_changed() is True

    def test_multiple_feeds_before_get_text(self):
        ts = TerminalScreen()
        ts.feed(b"a")
        ts.feed(b"b")
        ts.feed(b"c")
        assert ts.has_changed() is True
        ts.get_text()
        assert ts.has_changed() is False


class TestGetCursorPosition:
    """Tests for cursor position tracking."""

    def test_cursor_at_origin_initially(self):
        ts = TerminalScreen()
        assert ts.get_cursor_position() == (0, 0)

    def test_cursor_moves_after_text(self):
        ts = TerminalScreen(cols=80, rows=24)
        ts.feed(b"Hello")
        row, col = ts.get_cursor_position()
        assert row == 0
        assert col == 5

    def test_cursor_moves_to_next_line(self):
        ts = TerminalScreen(cols=80, rows=24)
        ts.feed(b"Hello\r\n")
        row, col = ts.get_cursor_position()
        assert row == 1
        assert col == 0

    def test_cursor_returns_tuple(self):
        ts = TerminalScreen()
        pos = ts.get_cursor_position()
        assert isinstance(pos, tuple)
        assert len(pos) == 2


class TestAnsiEscapeHandling:
    """Tests for ANSI escape sequence processing via pyte."""

    def test_clear_screen_escape(self):
        ts = TerminalScreen(cols=80, rows=24)
        ts.feed(b"Hello")
        # ESC[2J clears the screen, ESC[H moves cursor home
        ts.feed(b"\x1b[2J\x1b[H")
        text = ts.get_text()
        lines = text.split("\n")
        # Screen should be cleared
        for line in lines:
            assert line == ""

    def test_cursor_movement_escape(self):
        ts = TerminalScreen(cols=80, rows=24)
        # ESC[3;5H moves cursor to row 3, col 5 (1-based in ANSI)
        ts.feed(b"\x1b[3;5HX")
        text = ts.get_text()
        lines = text.split("\n")
        # Row 2 (0-indexed), col 4 (0-indexed) should have 'X'
        assert lines[2][4] == "X"

    def test_color_codes_stripped_from_text(self):
        ts = TerminalScreen(cols=80, rows=24)
        # Red text "Hi" then reset
        ts.feed(b"\x1b[31mHi\x1b[0m")
        text = ts.get_text()
        lines = text.split("\n")
        assert lines[0] == "Hi"
