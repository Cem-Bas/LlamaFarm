"""Keystroke engine — maps agent action dicts to raw bytes for PTY input.

Sits between the Ollama client (which returns action dicts) and the PTY
manager (which accepts raw bytes).  Zero external dependencies.

Exports
-------
encode_action(action: dict) -> bytes | None
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Key mapping tables
# ---------------------------------------------------------------------------

_SPECIAL_KEYS: dict[str, bytes] = {
    # Single-byte keys
    "enter":     b"\r",
    "tab":       b"\t",
    "escape":    b"\x1b",
    "backspace": b"\x7f",
    # Multi-byte escape sequences
    "delete":    b"\x1b[3~",
    # Arrow keys
    "up":        b"\x1b[A",
    "down":      b"\x1b[B",
    "right":     b"\x1b[C",
    "left":      b"\x1b[D",
    # Navigation
    "home":      b"\x1b[H",
    "end":       b"\x1b[F",
    "pageup":    b"\x1b[5~",
    "pagedown":  b"\x1b[6~",
    # Function keys
    "f1":        b"\x1bOP",
    "f2":        b"\x1bOQ",
    "f3":        b"\x1bOR",
    "f4":        b"\x1bOS",
    "f5":        b"\x1b[15~",
    "f6":        b"\x1b[17~",
    "f7":        b"\x1b[18~",
    "f8":        b"\x1b[19~",
    "f9":        b"\x1b[20~",
    "f10":       b"\x1b[21~",
    "f11":       b"\x1b[23~",
    "f12":       b"\x1b[24~",
}


def _resolve_key(name: str) -> bytes:
    """Resolve a single key name (case-insensitive) to its byte sequence.

    Supports special keys from ``_SPECIAL_KEYS`` and ``ctrl+<letter>``
    combinations (ctrl+a through ctrl+z).

    Raises
    ------
    ValueError
        If *name* does not match any known key.
    """
    lower = name.lower().strip()

    # Check special-key table first
    if lower in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[lower]

    # ctrl+<letter>  →  \x01 .. \x1a
    if lower.startswith("ctrl+") and len(lower) == 6:
        letter = lower[5]
        if "a" <= letter <= "z":
            return bytes([ord(letter) - ord("a") + 1])

    raise ValueError(f"Unknown key: {name!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encode_action(action: dict) -> bytes | None:
    """Convert an agent action dict to raw bytes for PTY input.

    Parameters
    ----------
    action : dict
        Must contain ``"action"`` and ``"value"`` keys.

        Supported action types:

        * ``"type"``  – value is a string; returns UTF-8 encoded bytes.
        * ``"key"``   – value is a key name; returns the escape sequence.
        * ``"keys"``  – value is a list of key names; returns concatenated
          escape sequences.
        * ``"wait"``  – value is a number (seconds); returns ``None``.

    Returns
    -------
    bytes | None
        Raw bytes to write to the PTY, or ``None`` for wait actions.

    Raises
    ------
    ValueError
        If the action type is unknown or a key name is unrecognised.
    KeyError
        If required dict keys are missing.
    """
    action_type: str = action["action"]
    value = action["value"]

    if action_type == "type":
        return value.encode("utf-8")

    if action_type == "key":
        return _resolve_key(value)

    if action_type == "keys":
        return b"".join(_resolve_key(k) for k in value)

    if action_type == "wait":
        return None

    raise ValueError(f"Unknown action: {action_type!r}")
