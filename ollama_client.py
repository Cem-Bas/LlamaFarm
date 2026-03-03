"""Ollama client — sends terminal screen state to Ollama, receives action dicts.

Sits between the screen buffer (which provides screen text) and the agent
loop (which executes actions via the keystroke engine).

Exports
-------
OllamaAgent  — conversation-aware agent that returns structured action dicts.
SYSTEM_PROMPT — the system prompt defining agent behavior and JSON format.
"""

from __future__ import annotations

import json
import re

from ollama import chat

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an autonomous terminal agent. You observe the current terminal screen \
and decide what to do next. You MUST respond with ONLY a single JSON object — \
no markdown, no explanation, no extra text.

Your response must be one of these four action formats:

1. Type text into the terminal:
   {"action": "type", "value": "<text to type>"}

2. Press a single special key:
   {"action": "key", "value": "<key name>"}

3. Press a sequence of special keys:
   {"action": "keys", "value": ["<key1>", "<key2>", ...]}

4. Wait and observe (seconds):
   {"action": "wait", "value": <number>}

Available keys: enter, tab, escape, backspace, delete, \
up, down, left, right, home, end, pageup, pagedown, \
f1-f12, ctrl+a through ctrl+z.

Rules:
- Always respond with valid JSON only.
- After typing a command, send enter as a separate key action — do NOT \
include a newline in the type value.
- Use wait when output is still being generated or you need to observe \
the result of a previous action.
- If you are unsure what to do, use wait with a value of 2.\
"""

# ---------------------------------------------------------------------------
# Fallback action returned on any error
# ---------------------------------------------------------------------------

_FALLBACK_ACTION: dict = {"action": "wait", "value": 2}

# Regex to extract JSON from markdown code blocks
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# ---------------------------------------------------------------------------
# OllamaAgent
# ---------------------------------------------------------------------------

class OllamaAgent:
    """Conversation-aware Ollama agent that returns structured action dicts.

    Parameters
    ----------
    model : str
        Ollama model name (e.g. ``"qwen3-coder:30b"``).
    max_history : int
        Maximum number of message *pairs* (user + assistant) to retain
        in the rolling conversation window.
    """

    def __init__(self, model: str, max_history: int = 20) -> None:
        self.model = model
        self.max_history = max_history
        self._history: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide(self, screen_text: str) -> dict:
        """Send the current screen state to Ollama and return an action dict.

        On any error (network, malformed JSON, unexpected exception) the
        method returns the safe fallback ``{"action": "wait", "value": 2}``.
        """
        try:
            messages = self._build_messages(screen_text)

            response = chat(
                model=self.model,
                messages=messages,
                format="json",
                options={"temperature": 0.1, "num_predict": 256},
            )

            content: str = response.message.content
            action = self._parse_response(content)

            # Append the exchange to history
            self._history.append({"role": "user", "content": screen_text})
            self._history.append({"role": "assistant", "content": content})

            # Trim history to max_history pairs (each pair = 2 messages)
            max_messages = self.max_history * 2
            if len(self._history) > max_messages:
                self._history = self._history[-max_messages:]

            return action

        except Exception:
            return dict(_FALLBACK_ACTION)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(self, screen_text: str) -> list[dict[str, str]]:
        """Assemble the full message list: system + history + current user."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        messages.extend(self._history)
        messages.append({"role": "user", "content": screen_text})
        return messages

    def _parse_response(self, content: str) -> dict:
        """Parse a JSON action dict from the model's response text.

        Tries ``json.loads`` first, then falls back to regex extraction
        from markdown code blocks.  Returns the fallback wait action if
        all parsing attempts fail.
        """
        # Attempt 1: direct JSON parse
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass

        # Attempt 2: extract from markdown ```json ... ``` block
        match = _JSON_BLOCK_RE.search(content)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # All attempts failed — return safe fallback
        return dict(_FALLBACK_ACTION)
