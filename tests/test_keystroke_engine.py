"""Tests for keystroke_engine — maps agent action dicts to raw PTY bytes."""

import pytest

from keystroke_engine import encode_action


# ---------------------------------------------------------------------------
# 1. Action: "type" — plain text → UTF-8 bytes
# ---------------------------------------------------------------------------

class TestTypeAction:
    def test_simple_ascii(self):
        assert encode_action({"action": "type", "value": "ls -la"}) == b"ls -la"

    def test_empty_string(self):
        assert encode_action({"action": "type", "value": ""}) == b""

    def test_unicode(self):
        assert encode_action({"action": "type", "value": "héllo"}) == "héllo".encode("utf-8")

    def test_multiline(self):
        assert encode_action({"action": "type", "value": "a\nb"}) == b"a\nb"

    def test_special_chars(self):
        assert encode_action({"action": "type", "value": "echo $HOME"}) == b"echo $HOME"

    def test_long_command(self):
        cmd = "find / -name '*.py' -exec grep -l 'import os' {} +"
        assert encode_action({"action": "type", "value": cmd}) == cmd.encode("utf-8")


# ---------------------------------------------------------------------------
# 2. Action: "key" — single special key → escape sequence
# ---------------------------------------------------------------------------

class TestKeyAction:
    # --- simple single-byte keys ---
    def test_enter(self):
        assert encode_action({"action": "key", "value": "enter"}) == b"\r"

    def test_tab(self):
        assert encode_action({"action": "key", "value": "tab"}) == b"\t"

    def test_escape(self):
        assert encode_action({"action": "key", "value": "escape"}) == b"\x1b"

    def test_backspace(self):
        assert encode_action({"action": "key", "value": "backspace"}) == b"\x7f"

    # --- multi-byte escape sequences ---
    def test_delete(self):
        assert encode_action({"action": "key", "value": "delete"}) == b"\x1b[3~"

    # --- arrow keys ---
    def test_up(self):
        assert encode_action({"action": "key", "value": "up"}) == b"\x1b[A"

    def test_down(self):
        assert encode_action({"action": "key", "value": "down"}) == b"\x1b[B"

    def test_right(self):
        assert encode_action({"action": "key", "value": "right"}) == b"\x1b[C"

    def test_left(self):
        assert encode_action({"action": "key", "value": "left"}) == b"\x1b[D"

    # --- navigation ---
    def test_home(self):
        assert encode_action({"action": "key", "value": "home"}) == b"\x1b[H"

    def test_end(self):
        assert encode_action({"action": "key", "value": "end"}) == b"\x1b[F"

    def test_pageup(self):
        assert encode_action({"action": "key", "value": "pageup"}) == b"\x1b[5~"

    def test_pagedown(self):
        assert encode_action({"action": "key", "value": "pagedown"}) == b"\x1b[6~"

    # --- function keys ---
    def test_f1(self):
        assert encode_action({"action": "key", "value": "f1"}) == b"\x1bOP"

    def test_f2(self):
        assert encode_action({"action": "key", "value": "f2"}) == b"\x1bOQ"

    def test_f3(self):
        assert encode_action({"action": "key", "value": "f3"}) == b"\x1bOR"

    def test_f4(self):
        assert encode_action({"action": "key", "value": "f4"}) == b"\x1bOS"

    def test_f5(self):
        assert encode_action({"action": "key", "value": "f5"}) == b"\x1b[15~"

    def test_f6(self):
        assert encode_action({"action": "key", "value": "f6"}) == b"\x1b[17~"

    def test_f7(self):
        assert encode_action({"action": "key", "value": "f7"}) == b"\x1b[18~"

    def test_f8(self):
        assert encode_action({"action": "key", "value": "f8"}) == b"\x1b[19~"

    def test_f9(self):
        assert encode_action({"action": "key", "value": "f9"}) == b"\x1b[20~"

    def test_f10(self):
        assert encode_action({"action": "key", "value": "f10"}) == b"\x1b[21~"

    def test_f11(self):
        assert encode_action({"action": "key", "value": "f11"}) == b"\x1b[23~"

    def test_f12(self):
        assert encode_action({"action": "key", "value": "f12"}) == b"\x1b[24~"

    # --- ctrl combinations ---
    def test_ctrl_c(self):
        assert encode_action({"action": "key", "value": "ctrl+c"}) == b"\x03"

    def test_ctrl_a(self):
        assert encode_action({"action": "key", "value": "ctrl+a"}) == b"\x01"

    def test_ctrl_z(self):
        assert encode_action({"action": "key", "value": "ctrl+z"}) == b"\x1a"

    def test_ctrl_d(self):
        assert encode_action({"action": "key", "value": "ctrl+d"}) == b"\x04"

    def test_ctrl_l(self):
        assert encode_action({"action": "key", "value": "ctrl+l"}) == b"\x0c"

    # --- case insensitivity ---
    def test_case_insensitive_key(self):
        assert encode_action({"action": "key", "value": "Enter"}) == b"\r"
        assert encode_action({"action": "key", "value": "ENTER"}) == b"\r"

    def test_case_insensitive_ctrl(self):
        assert encode_action({"action": "key", "value": "Ctrl+C"}) == b"\x03"
        assert encode_action({"action": "key", "value": "CTRL+C"}) == b"\x03"

    # --- unknown key ---
    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match="Unknown key"):
            encode_action({"action": "key", "value": "nosuchkey"})


# ---------------------------------------------------------------------------
# 3. Action: "keys" — sequence of keys → concatenated bytes
# ---------------------------------------------------------------------------

class TestKeysAction:
    def test_single_key_sequence(self):
        result = encode_action({"action": "keys", "value": ["enter"]})
        assert result == b"\r"

    def test_multi_key_sequence(self):
        result = encode_action({"action": "keys", "value": ["ctrl+c", "up"]})
        assert result == b"\x03\x1b[A"

    def test_complex_sequence(self):
        result = encode_action({"action": "keys", "value": ["escape", "up", "up", "enter"]})
        assert result == b"\x1b\x1b[A\x1b[A\r"

    def test_empty_sequence(self):
        result = encode_action({"action": "keys", "value": []})
        assert result == b""

    def test_function_key_sequence(self):
        result = encode_action({"action": "keys", "value": ["f1", "f12"]})
        assert result == b"\x1bOP\x1b[24~"

    def test_unknown_key_in_sequence_raises(self):
        with pytest.raises(ValueError, match="Unknown key"):
            encode_action({"action": "keys", "value": ["enter", "badkey"]})


# ---------------------------------------------------------------------------
# 4. Action: "wait" — return None
# ---------------------------------------------------------------------------

class TestWaitAction:
    def test_wait_returns_none(self):
        assert encode_action({"action": "wait", "value": 2}) is None

    def test_wait_float(self):
        assert encode_action({"action": "wait", "value": 0.5}) is None

    def test_wait_zero(self):
        assert encode_action({"action": "wait", "value": 0}) is None


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_unknown_action_raises(self):
        with pytest.raises(ValueError, match="Unknown action"):
            encode_action({"action": "click", "value": "button"})

    def test_missing_action_key_raises(self):
        with pytest.raises((ValueError, KeyError)):
            encode_action({"value": "hello"})

    def test_missing_value_key_raises(self):
        with pytest.raises((ValueError, KeyError)):
            encode_action({"action": "type"})


# ---------------------------------------------------------------------------
# 6. Ctrl key coverage — full alphabet
# ---------------------------------------------------------------------------

class TestCtrlFullAlphabet:
    @pytest.mark.parametrize(
        "letter,expected_byte",
        [(chr(ord("a") + i), bytes([i + 1])) for i in range(26)],
    )
    def test_ctrl_letter(self, letter, expected_byte):
        result = encode_action({"action": "key", "value": f"ctrl+{letter}"})
        assert result == expected_byte

    @pytest.mark.parametrize(
        "letter,expected_byte",
        [(chr(ord("A") + i), bytes([i + 1])) for i in range(26)],
    )
    def test_ctrl_uppercase_letter(self, letter, expected_byte):
        result = encode_action({"action": "key", "value": f"ctrl+{letter}"})
        assert result == expected_byte
