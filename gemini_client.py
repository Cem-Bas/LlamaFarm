"""Gemini CLI agent — runs gemini in a PTY and communicates via terminal I/O.

Spawns the `gemini` CLI process, types prompts into it, reads responses
from the terminal screen buffer. Drop-in replacement for OllamaAgent
when used as orchestrator.

Exports
-------
GeminiCLIAgent — PTY-based agent using the Gemini CLI.
"""

from __future__ import annotations

import json
import re
import shutil
import time

from ollama_client import ORCHESTRATOR_SYSTEM_PROMPT, _FALLBACK_ACTION, _JSON_BLOCK_RE
from pty_manager import PTYManager
from screen import TerminalScreen
from config import SCREEN_COLS, SCREEN_ROWS


class GeminiCLIAgent:
    """Orchestrator agent that uses the Gemini CLI via a PTY.

    Mirrors the OllamaAgent interface (model, orchestrator, _history, decide())
    so SwarmManager can use it as a drop-in replacement.

    Parameters
    ----------
    max_history : int
        Unused — kept for interface compat.
    """

    def __init__(self, model: str = "gemini", max_history: int = 20, orchestrator: bool = True) -> None:
        self.model = "gemini-cli"
        self.max_history = max_history
        self.orchestrator = orchestrator
        self._history: list[dict[str, str]] = []
        self._pty: PTYManager | None = None
        self._screen: TerminalScreen | None = None
        self._booted = False
        self._system_sent = False

    def _boot(self) -> None:
        """Spawn the gemini CLI process."""
        if self._booted:
            return
        self._pty = PTYManager(shell=shutil.which("gemini") or "gemini", cols=SCREEN_COLS, rows=SCREEN_ROWS)
        self._screen = TerminalScreen(cols=SCREEN_COLS, rows=SCREEN_ROWS)
        self._pty.spawn()
        self._booted = True
        # Wait for gemini to start up
        self._wait_for_prompt(timeout=10)

    def _read_screen(self) -> str:
        """Read PTY output and return screen text."""
        data = self._pty.read(timeout=0.2)
        if data:
            self._screen.feed(data)
        lines = [self._screen._screen.display[row].rstrip()
                 for row in range(self._screen._screen.lines)]
        return "\n".join(lines)

    def _drain_output(self, timeout: float = 1.0) -> str:
        """Keep reading until output stops changing."""
        last = ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self._read_screen()
            if text != last:
                last = text
                deadline = time.time() + timeout  # reset on new output
            time.sleep(0.1)
        return last

    def _wait_for_prompt(self, timeout: float = 10) -> str:
        """Wait for gemini CLI to show its input prompt."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self._read_screen()
            # Gemini CLI typically shows a ">" or "❯" prompt when ready
            if text.strip():
                time.sleep(1)  # extra settle time
                return self._drain_output(timeout=1.0)
            time.sleep(0.3)
        return self._read_screen()

    def _type_text(self, text: str) -> None:
        """Type text into the gemini PTY."""
        self._pty.write(text.encode())

    def _press_enter(self) -> None:
        """Send Enter key."""
        self._pty.write(b"\r")

    def _send_prompt(self, prompt: str) -> str:
        """Type a prompt into gemini and wait for the response."""
        # Clear any stale output by reading
        self._drain_output(timeout=0.3)

        # Capture screen before typing so we can detect new output
        before = self._read_screen()

        # Type the prompt (escape newlines for terminal input)
        # Gemini CLI accepts multiline via shift+enter or we can send it all at once
        # Simplest: send as a single long line
        single_line = prompt.replace("\n", " | ")
        self._type_text(single_line)
        self._press_enter()

        # Wait for response — gemini takes a few seconds
        time.sleep(2)

        # Keep reading until output stabilises (gemini streams)
        response_text = self._drain_output(timeout=3.0)

        return response_text

    def _extract_json_from_screen(self, screen: str, prompt_snippet: str = "") -> dict:
        """Try to extract a JSON command dict from gemini's screen output."""
        # Look for JSON blocks in the screen text
        # Try to find the last JSON object in the output
        json_pattern = re.compile(r'\{[^{}]*"command"\s*:\s*"[^"]*"[^{}]*\}')
        matches = json_pattern.findall(screen)
        if matches:
            # Use the last match (most recent response)
            for match in reversed(matches):
                try:
                    return json.loads(match)
                except (json.JSONDecodeError, TypeError):
                    continue

        # Try markdown block extraction
        block_match = _JSON_BLOCK_RE.search(screen)
        if block_match:
            try:
                return json.loads(block_match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # Try to find any JSON object
        generic_pattern = re.compile(r'\{[^{}]+\}')
        for m in reversed(generic_pattern.findall(screen)):
            try:
                parsed = json.loads(m)
                if "command" in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                continue

        return dict(_FALLBACK_ACTION)

    # ------------------------------------------------------------------
    # Public API — matches OllamaAgent interface
    # ------------------------------------------------------------------

    def decide(self, screen_text: str) -> dict:
        """Send swarm status to Gemini CLI and return a command dict."""
        try:
            self._boot()

            # Send system prompt on first call
            if not self._system_sent:
                sys_prompt = (
                    "You are a swarm orchestrator. "
                    "From now on, I will send you worker status updates. "
                    "Reply with ONLY a single JSON object, no markdown, no explanation. "
                    "Commands: "
                    '{"command":"spawn","shell_cmd":"<cmd>"} | '
                    '{"command":"assign","worker":"<id>","goal":"<goal>"} | '
                    '{"command":"kill","worker":"<id>"} | '
                    '{"command":"wait","value":<n>} '
                    "Workers run macOS zsh shell commands (ls, find, cat, etc). "
                    "Spawn at most 3 workers. Reply ONLY with JSON."
                )
                self._send_prompt(sys_prompt)
                self._system_sent = True
                time.sleep(1)

            # Send the actual swarm status
            response_screen = self._send_prompt(screen_text)
            command = self._extract_json_from_screen(response_screen)

            print(f"[Gemini CLI] Raw screen response (last 5 lines):")
            for line in response_screen.strip().split("\n")[-5:]:
                if line.strip():
                    print(f"  {line}")

            # Store in history for compat
            self._history.append({"role": "user", "content": screen_text})
            self._history.append({"role": "assistant", "content": json.dumps(command)})

            return command

        except Exception as e:
            print(f"[Gemini CLI] Error: {e}")
            return dict(_FALLBACK_ACTION)
