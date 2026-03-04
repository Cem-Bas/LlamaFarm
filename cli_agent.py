"""Terminal CLI Agent — generic PTY-based agent for gemini, claude, and codex CLIs.

Spawns a CLI tool (gemini, claude, or codex) in a pseudo-terminal, types
prompts into it, and reads responses from the terminal screen buffer.
Drop-in replacement for OllamaAgent when used as orchestrator or worker.

Exports
-------
TerminalCLIAgent — PTY-based agent supporting multiple CLI backends.
CLI_BACKENDS     — registry of supported CLI tools and their configurations.
"""

from __future__ import annotations

import json
import re
import shutil
import time

from ollama_client import SYSTEM_PROMPT, ORCHESTRATOR_SYSTEM_PROMPT, _FALLBACK_ACTION, _JSON_BLOCK_RE

# Strip ANSI escape sequences from raw output
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b[()][0-9A-B]|\x1b\[[\?]?[0-9;]*[hlm]')

# ---------------------------------------------------------------------------
# CLI backend registry
# ---------------------------------------------------------------------------

CLI_BACKENDS: dict[str, dict] = {
    "gemini": {
        "binary": shutil.which("gemini") or "gemini",
        "display_name": "Gemini CLI",
        "startup_wait": 12,
        "response_wait": 8,
        "drain_timeout": 12.0,
        "prompt_indicator": "",  # gemini shows various prompts
    },
    "claude": {
        "binary": shutil.which("claude") or "claude",
        "display_name": "Claude CLI",
        "startup_wait": 10,
        "response_wait": 5,
        "drain_timeout": 10.0,
        "prompt_indicator": "",
        "args": ["--dangerously-skip-permissions"],  # non-interactive mode
    },
    "codex": {
        "binary": shutil.which("codex") or "codex",
        "display_name": "Codex CLI",
        "startup_wait": 10,
        "response_wait": 5,
        "drain_timeout": 10.0,
        "prompt_indicator": "",
        "args": ["exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check",
                 "-o", "/tmp/codex_last_msg.txt"],
        "subprocess": True,  # use subprocess.run instead of PTY
        "output_file": "/tmp/codex_last_msg.txt",  # codex writes last message here
    },
}

# Regex to find JSON with "command" key (orchestrator responses)
_CMD_JSON_RE = re.compile(r'\{[^{}]*"command"\s*:\s*"[^"]*"[^{}]*\}')
# Regex to find JSON with "action" key (worker responses)
_ACTION_JSON_RE = re.compile(r'\{[^{}]*"action"\s*:\s*"[^"]*"[^{}]*\}')


class TerminalCLIAgent:
    """Generic PTY-based CLI agent supporting gemini, claude, and codex.

    Mirrors the OllamaAgent interface (model, orchestrator, _history, decide())
    so SwarmManager and TerminalAgent can use it as a drop-in replacement.

    Parameters
    ----------
    cli_name : str
        Name of the CLI backend ("gemini", "claude", or "codex").
    orchestrator : bool
        When True, use orchestrator system prompt; otherwise use worker prompt.
    max_history : int
        Unused — kept for interface compat with OllamaAgent.
    """

    def __init__(
        self,
        cli_name: str = "gemini",
        orchestrator: bool = False,
        max_history: int = 20,
    ) -> None:
        if cli_name not in CLI_BACKENDS:
            raise ValueError(f"Unknown CLI backend: {cli_name!r}. Use one of: {list(CLI_BACKENDS.keys())}")

        self._backend = CLI_BACKENDS[cli_name]
        self.model = f"{cli_name}-cli"
        self.cli_name = cli_name
        self.max_history = max_history
        self.orchestrator = orchestrator
        self.goal: str = ""
        self._history: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # PTY-based one-shot execution
    # ------------------------------------------------------------------

    def _run_prompt(self, prompt: str) -> str:
        """Run the CLI with a prompt and return the output.

        Uses subprocess for CLIs that support non-interactive mode (codex exec),
        or PTY for CLIs that require a terminal (gemini, claude).
        """
        import os
        import subprocess

        binary = self._backend["binary"]
        args = self._backend.get("args", [])
        name = self._backend["display_name"]
        use_subprocess = self._backend.get("subprocess", False)

        if use_subprocess:
            # Non-interactive mode — codex exec works with piped I/O
            output_file = self._backend.get("output_file", "")
            # Clear output file before run
            if output_file:
                try:
                    os.remove(output_file)
                except FileNotFoundError:
                    pass

            cmd = [binary] + args + [prompt]
            timeout = 120
            try:
                print(f"[{name}] Running: {' '.join(cmd[:4])}... ({len(prompt)} chars)")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
                )
                output = result.stdout + "\n" + result.stderr

                # Also read from output file if available (codex -o flag)
                if output_file:
                    try:
                        with open(output_file, "r") as f:
                            file_content = f.read().strip()
                        if file_content:
                            print(f"[{name}] Output file ({len(file_content)} chars): {file_content[:200]}")
                            output = file_content + "\n" + output
                    except FileNotFoundError:
                        pass

                return output
            except subprocess.TimeoutExpired:
                print(f"[{name}] Timed out after {timeout}s")
                return ""
            except Exception as e:
                print(f"[{name}] Error: {e}")
                return ""
        else:
            # PTY mode — for CLIs that need a terminal (gemini, claude)
            from pty_manager import PTYManager

            pty = PTYManager(shell="/bin/sh", cols=200, rows=100)
            pty.spawn()

            safe_prompt = prompt.replace("'", "'\\''")
            cmd = f"{binary} {' '.join(args)} '{safe_prompt}'\n"
            time.sleep(0.3)
            pty.write(cmd.encode())

            chunks: list[str] = []
            wait_time = self._backend["response_wait"]
            drain_time = self._backend["drain_timeout"]
            time.sleep(wait_time)

            deadline = time.time() + drain_time
            while time.time() < deadline:
                data = pty.read(timeout=0.3)
                if data:
                    text = data.decode("utf-8", errors="replace")
                    chunks.append(text)
                    deadline = time.time() + drain_time

                    # Handle Claude's safety acceptance dialog
                    if "Yes, I accept" in text or "Enter to confirm" in text:
                        time.sleep(0.3)
                        pty.write(b"\x1b[B")  # down arrow
                        time.sleep(0.2)
                        pty.write(b"\r")      # enter
                        deadline = time.time() + drain_time
                time.sleep(0.1)

            pty.close()
            return "".join(chunks)

    def close(self) -> None:
        """No persistent state to close."""
        pass

    # ------------------------------------------------------------------
    # JSON extraction
    # ------------------------------------------------------------------

    def _extract_json(self, raw_text: str) -> dict:
        """Extract a JSON dict from CLI raw output.

        For orchestrator mode, looks for {"command": ...}.
        For worker mode, looks for {"action": ...}.
        Strips ANSI escape codes before searching.
        """
        # Strip ANSI escape codes from raw PTY output
        clean = _ANSI_RE.sub("", raw_text)

        pattern = _CMD_JSON_RE if self.orchestrator else _ACTION_JSON_RE
        key = "command" if self.orchestrator else "action"

        # Try specific pattern first
        matches = pattern.findall(clean)
        if matches:
            for match in reversed(matches):
                try:
                    parsed = json.loads(match)
                    if key in parsed:
                        return parsed
                except (json.JSONDecodeError, TypeError):
                    continue

        # Try markdown block extraction
        block_match = _JSON_BLOCK_RE.search(clean)
        if block_match:
            try:
                parsed = json.loads(block_match.group(1))
                if key in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Try any JSON object with the right key
        generic = re.compile(r'\{[^{}]+\}')
        for m in reversed(generic.findall(clean)):
            try:
                parsed = json.loads(m)
                if key in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                continue

        return dict(_FALLBACK_ACTION)

    # ------------------------------------------------------------------
    # System prompt helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the first interaction."""
        if self.orchestrator:
            mission = self.goal or "Follow user instructions"
            prompt = (
                f"MISSION: {mission}\n"
                f"Accomplish this mission: {mission}\n"
                "You are a swarm orchestrator on macOS. Output ONLY a JSON object.\n"
                "Commands: spawn, assign, kill, wait\n"
                "Keys: command, goal, worker, value, reply\n"
                "Each worker runs an AI agent autonomously. Give them goals, not shell commands.\n"
                "If 0 workers, spawn one with a goal that serves the mission.\n"
                "Do NOT kill workers that are starting up or actively working. Be patient.\n"
                "Include reply when answering USER MESSAGES.\n"
            )
            return prompt
        else:
            # Worker mode — instruct the CLI to act as a terminal agent
            prompt = (
                "You are a terminal agent on macOS with zsh. "
                "You observe terminal screen text and decide the next action. "
                "Reply with ONLY a JSON object.\n"
                "Actions: type, key, wait\n"
                "Keys: action, value\n"
                "FORBIDDEN: ctrl+c, ctrl+z, any ctrl keys, the keys action.\n"
                "FORBIDDEN: running codex, gemini, claude, ollama, or any AI tool as a command.\n"
                "After typing a command, send a SEPARATE action to press enter.\n"
            )
            if self.goal:
                prompt += f"Your GOAL: {self.goal}\nWork toward this goal. Stay focused.\n"
            return prompt

    # ------------------------------------------------------------------
    # Public API — matches OllamaAgent interface
    # ------------------------------------------------------------------

    def decide(self, screen_text: str) -> dict:
        """Send input to the CLI and return a command/action dict."""
        try:
            # Build the full prompt: system context + input
            sys_prompt = self._build_system_prompt()
            full_prompt = f"{sys_prompt}\n\n{screen_text}"

            # Run CLI as subprocess
            raw_response = self._run_prompt(full_prompt)
            result = self._extract_json(raw_response)

            # Log response — strip ANSI for readable output
            name = self._backend["display_name"]
            clean = _ANSI_RE.sub("", raw_response)
            non_empty = [l for l in clean.split("\n") if l.strip()]
            print(f"[{name}] Output: {len(raw_response)} chars, {len(non_empty)} lines")
            for line in non_empty[-8:]:
                print(f"  {line.rstrip()[:120]}")
            print(f"[{name}] Extracted: {json.dumps(result)}")

            # Store in history for compat
            self._history.append({"role": "user", "content": screen_text})
            self._history.append({"role": "assistant", "content": json.dumps(result)})

            return result

        except Exception as e:
            name = self._backend.get("display_name", self.cli_name)
            print(f"[{name}] Error: {e}")
            import traceback
            traceback.print_exc()
            return dict(_FALLBACK_ACTION)
