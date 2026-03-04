"""Ollama client — sends terminal screen state to Ollama, receives action dicts.

Sits between the screen buffer (which provides screen text) and the agent
loop (which executes actions via the keystroke engine).

Exports
-------
OllamaAgent  — conversation-aware agent that returns structured action dicts.
SYSTEM_PROMPT — the system prompt defining agent behavior and JSON format.
ORCHESTRATOR_SYSTEM_PROMPT — the system prompt for swarm orchestrator mode.
"""

from __future__ import annotations

import json
import re

from ollama import chat

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an autonomous terminal agent on macOS with zsh. You have a GOAL and \
you work step by step to accomplish it using shell commands. You observe the \
terminal screen and decide your next action. Respond with ONLY a JSON object.

Actions (pick ONE):

{"action": "type", "value": "ls -la"}     — type text (NO newline at end)
{"action": "key", "value": "enter"}       — press a key to submit a command
{"action": "wait", "value": 2}            — wait N seconds

You may add a "reply" field to ANY action to respond to [USER MESSAGE]:
{"action": "type", "value": "ls", "reply": "Sure, listing files now."}

WORKFLOW — To run a command, do TWO separate actions:
  First:  {"action": "type", "value": "ls -la"}
  Then:   {"action": "key", "value": "enter"}

IMPORTANT RULES:
- When you see a shell prompt (ending with % or $), type a command. Do NOT wait.
- NEVER send ctrl+c, ctrl+z, or ctrl+\\. These are FORBIDDEN.
- NEVER use the "keys" action. Only use "type", "key", or "wait".
- Only use "wait" AFTER running a command, to let output appear.
- Work toward your assigned GOAL. Each action should make progress.
- Read command output before running the next command.
- NEVER use rm, sudo, kill, shutdown, reboot, mkfs, dd, or any destructive commands.
- NEVER access /etc/passwd, /etc/shadow, or other sensitive system files.
- Safe commands: ls, cat, find, head, tail, wc, du, df, ps, echo, pwd, whoami, \
grep, date, uptime, env, which, file, stat, tree, uname, sw_vers, top -l 1.\
"""

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are a swarm orchestrator on macOS. You manage AI-powered terminal workers.
Read worker status and decide what to do. Respond with ONLY ONE JSON object.

Commands: spawn, assign, kill, wait
Keys: command, shell_cmd, worker, goal, value, reply

RULES:
- If 0 workers exist, spawn ONE to accomplish the mission.
- If workers are already working (status=acting), you MUST use wait.
- NEVER spawn duplicate workers for the same goal.
- NEVER repeat your last command. Check YOUR LAST COMMAND.
- Only kill workers that have finished or errored.
- Include reply when answering USER MESSAGES.
- When in doubt, wait.\
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
    orchestrator : bool
        When ``True``, use the orchestrator system prompt instead of the
        default worker system prompt.
    """

    def __init__(self, model: str, max_history: int = 20, orchestrator: bool = False) -> None:
        self.model = model
        self.max_history = max_history
        self.orchestrator = orchestrator
        self.goal: str = ""
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
                options={"temperature": 0.1, "num_predict": 256, "num_ctx": 8192},
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
        prompt = ORCHESTRATOR_SYSTEM_PROMPT if self.orchestrator else SYSTEM_PROMPT
        # Inject goal into system prompt so the model always knows what to do
        if self.goal and not self.orchestrator:
            prompt += f"\n\nYour GOAL: {self.goal}\nWork toward this goal step by step."
        messages: list[dict[str, str]] = [
            {"role": "system", "content": prompt},
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
