"""Agent loop — wires PTYManager, TerminalScreen, OllamaAgent, and encode_action
into an Observe-Think-Act cycle.

This is the core autonomous terminal agent. Each iteration:
1. **Observe**: Read PTY output into the virtual screen buffer.
2. **Think**: Send screen text to Ollama and receive an action dict.
3. **Act**: Encode the action and write raw bytes to the PTY (or wait).

Exports
-------
TerminalAgent — the main agent class.
main          — basic entry-point function.
"""

from __future__ import annotations

import json
import signal
import sys
import time

from config import (
    MODEL,
    SCREEN_COLS,
    SCREEN_ROWS,
    SHELL,
    MAX_HISTORY,
    OBSERVE_TIMEOUT,
    WEB_HOST,
    WEB_PORT,
    is_cli_agent,
)
import re

from cli_agent import TerminalCLIAgent
from keystroke_engine import encode_action
from ollama_client import OllamaAgent
from pty_manager import PTYManager
from screen import TerminalScreen
from web.server import broadcast as web_broadcast, app as web_app

# ---------------------------------------------------------------------------
# Safety — block destructive commands before they reach the PTY
# ---------------------------------------------------------------------------

_DANGEROUS_PATTERNS = [
    re.compile(r'\brm\s+-(r|f|rf|fr)', re.IGNORECASE),  # rm -rf, rm -f, rm -r
    re.compile(r'\brm\b.*\*'),                             # rm with wildcards
    re.compile(r'\bmkfs\b'),                                # format filesystem
    re.compile(r'\bdd\b\s+if='),                            # disk overwrite
    re.compile(r'>\s*/dev/sd'),                             # overwrite disk device
    re.compile(r'\bsudo\b'),                                # privilege escalation
    re.compile(r'\bchmod\s+777'),                           # world-writable
    re.compile(r'\bcurl\b.*\|\s*(ba)?sh'),                  # pipe curl to shell
    re.compile(r'\bwget\b.*\|\s*(ba)?sh'),                  # pipe wget to shell
    re.compile(r'\b:()\s*\{'),                              # fork bomb
    re.compile(r'/etc/passwd'),                             # password file access
    re.compile(r'/etc/shadow'),                             # shadow file access
    re.compile(r'\bshutdown\b'),                            # shutdown
    re.compile(r'\breboot\b'),                              # reboot
    re.compile(r'\bkill\s+-9\b'),                           # force kill
    re.compile(r'\bkillall\b'),                             # kill all processes
    re.compile(r'\bxargs\b.*\brm\b'),                       # xargs rm
    re.compile(r'\bformat\b'),                              # format
]


def _is_safe_action(action: dict) -> bool:
    """Return False if the action contains a dangerous command or blocked key combo."""
    act = action.get("action", "")

    # Block ctrl+c / ctrl+z — workers should never interrupt or suspend
    if act == "keys":
        vals = action.get("value", [])
        for v in vals:
            if isinstance(v, str) and v.lower() in ("ctrl+c", "ctrl+z", "ctrl+\\"):
                return False
        return True

    if act != "type":
        return True
    text = action.get("value", "")
    # Block AI tools from being run as shell commands
    stripped = text.strip().split()[0] if text.strip() else ""
    if stripped.lower() in ("codex", "gemini", "claude", "ollama", "chatgpt", "gpt"):
        return False
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(text):
            return False
    return True


class TerminalAgent:
    """Autonomous terminal agent using an Observe-Think-Act loop.

    Wires together a pseudo-terminal, a virtual screen buffer, and an
    Ollama-backed decision engine to operate a shell autonomously.

    Parameters
    ----------
    model : str
        Ollama model name.
    cols, rows : int
        Terminal dimensions.
    shell : str
        Path to the shell executable.
    max_history : int
        Maximum conversation history pairs for the Ollama agent.
    web_enabled : bool
        Whether the web UI broadcast is active (placeholder for Task 6).
    agent_id : str
        Unique identifier for this agent instance (used by swarm manager).
    goal : str
        High-level goal description for this agent.
    """

    def __init__(
        self,
        model: str = MODEL,
        cols: int = SCREEN_COLS,
        rows: int = SCREEN_ROWS,
        shell: str = SHELL,
        max_history: int = MAX_HISTORY,
        web_enabled: bool = True,
        agent_id: str = "agent-0",
        goal: str = "",
    ) -> None:
        self.agent_id = agent_id
        self.goal = goal
        self.web_enabled = web_enabled
        self.running = False
        self.iteration = 0
        self.last_action: dict | None = None
        self.status: str = "idle"
        self._uvicorn_loop = None  # set by main() after starting uvicorn
        self._is_cli = is_cli_agent(model)

        if self._is_cli:
            # CLI agent mode — the CLI itself is the "brain" AND the terminal
            # No separate PTY/screen needed for the shell; the CLI agent
            # manages its own PTY internally. But we still need a shell PTY
            # for the worker to execute commands in.
            self.pty = PTYManager(shell=shell, cols=cols, rows=rows)
            self.screen = TerminalScreen(cols=cols, rows=rows)
            cli_name = model.replace("-cli", "")  # "gemini-cli" -> "gemini"
            self.ollama = TerminalCLIAgent(
                cli_name=cli_name,
                orchestrator=False,
                max_history=max_history,
            )
            self.ollama.goal = goal
        else:
            # Ollama mode — standard PTY + OllamaAgent
            self.pty = PTYManager(shell=shell, cols=cols, rows=rows)
            self.screen = TerminalScreen(cols=cols, rows=rows)
            self.ollama = OllamaAgent(model=model, max_history=max_history)
            self.ollama.goal = goal

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the PTY shell and mark the agent as running."""
        self.pty.spawn()
        self.running = True

    def stop(self) -> None:
        """Stop the agent and close the PTY."""
        self.running = False
        self.pty.close()

    def get_snapshot(self) -> dict:
        """Return a read-only snapshot of this agent's current state.

        Reads the screen buffer directly to avoid resetting the _changed
        flag, which would interfere with run_loop's change detection when
        called from another thread (e.g. SwarmManager).
        """
        # Read screen display directly — do NOT call self.screen.get_text()
        # because that resets self.screen._changed as a side-effect.
        lines_raw = [self.screen._screen.display[row].rstrip()
                     for row in range(self.screen._screen.lines)]
        screen_text = "\n".join(lines_raw)
        # Last 5 non-empty lines as a compact summary
        lines = [l for l in screen_text.split("\n") if l.strip()]
        snippet = "\n".join(lines[-5:])
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "iteration": self.iteration,
            "last_action": dict(self.last_action) if self.last_action is not None else None,
            "screen_text": snippet,
            "goal": self.goal,
            "model": self.ollama.model,
        }

    # ------------------------------------------------------------------
    # Observe-Think-Act
    # ------------------------------------------------------------------

    def observe(self) -> str:
        """Read any available PTY output into the screen and return text.

        Returns the full screen buffer as a string regardless of whether
        new data arrived — the caller can compare with the previous text
        to detect unchanged screens.
        """
        data = self.pty.read(timeout=OBSERVE_TIMEOUT)
        if data:
            self.screen.feed(data)
        return self.screen.get_text()

    def think(self, screen_text: str) -> dict:
        """Ask the Ollama agent what to do given the current screen text.

        Returns an action dict, e.g. ``{"action": "type", "value": "ls"}``.
        """
        return self.ollama.decide(screen_text)

    def act(self, action: dict) -> None:
        """Execute an action dict on the PTY.

        For ``wait`` actions, sleeps for the specified duration.
        For all other actions, encodes to raw bytes and writes to the PTY.
        Dangerous commands are blocked and replaced with a safe wait.
        """
        if not _is_safe_action(action):
            print(f"[Agent] BLOCKED dangerous command: {action.get('value', '')}")
            self.last_action = {"action": "wait", "value": 1}
            time.sleep(1)
            return

        self.last_action = action
        raw = encode_action(action)
        if raw is None:
            # Wait action — sleep for the requested duration
            time.sleep(action.get("value", 1))
        else:
            self.pty.write(raw)

    # ------------------------------------------------------------------
    # Web broadcast placeholder (Task 6)
    # ------------------------------------------------------------------

    def _broadcast(self, event: str, data: dict) -> None:
        """Send screen state to WebSocket clients."""
        if not self.web_enabled:
            return
        try:
            import asyncio
            # Schedule the coroutine on uvicorn's event loop (running in another thread)
            loop = self._uvicorn_loop
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    web_broadcast(
                        data.get("screen_text", ""),
                        data.get("action", {}),
                        data.get("iteration", 0),
                    ),
                    loop,
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_loop(self) -> None:
        """Run the Observe-Think-Act loop until stopped or PTY dies."""
        cols = self.screen._screen.columns
        rows = self.screen._screen.lines
        print(f"[Agent] Model: {self.ollama.model}")
        print(f"[Agent] Screen: {cols}x{rows}")
        print(f"[Agent] Starting loop...")

        last_text = ""
        while self.running and self.pty.is_alive():
            try:
                self.status = "idle"

                # --- Observe ---
                screen_text = self.observe()

                # Skip iteration if screen hasn't changed
                if screen_text == last_text:
                    time.sleep(0.05)
                    continue
                last_text = screen_text

                self.iteration += 1

                # Clear terminal and display current state
                sys.stdout.write("\033[2J\033[H")
                print(f"--- Iteration {self.iteration} ---")
                print(screen_text)
                print("-" * 60)

                # --- Think ---
                self.status = "thinking"
                action = self.think(screen_text)
                print(f"[Action] {json.dumps(action)}")

                # --- Broadcast ---
                self._broadcast("action", {
                    "screen_text": screen_text,
                    "iteration": self.iteration,
                    "action": action,
                })

                # --- Act ---
                self.status = "acting"
                self.act(action)
                self.status = "idle"

            except KeyboardInterrupt:
                print("\n[Agent] Interrupted.")
                break
            except Exception as e:
                self.status = "error"
                print(f"\n[Agent] Error: {e}")
                time.sleep(1)

        self.stop()
        print("[Agent] Stopped.")


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main() -> None:
    import argparse
    import threading
    import uvicorn

    parser = argparse.ArgumentParser(description="Clawllama")
    parser.add_argument("--model", default=MODEL, help="Ollama model name")
    parser.add_argument("--goal", default=None, help="Initial goal for the agent")
    parser.add_argument("--no-web", action="store_true", help="Disable web UI")
    parser.add_argument("--cols", type=int, default=SCREEN_COLS, help="Terminal columns")
    parser.add_argument("--rows", type=int, default=SCREEN_ROWS, help="Terminal rows")
    parser.add_argument("--shell", default=SHELL, help="Shell executable")
    parser.add_argument("--port", type=int, default=WEB_PORT, help="Web UI port")
    args = parser.parse_args()

    agent = TerminalAgent(
        model=args.model,
        cols=args.cols,
        rows=args.rows,
        shell=args.shell,
        web_enabled=not args.no_web,
    )

    # Seed conversation with goal if provided
    if args.goal:
        agent.ollama._history.append({
            "role": "user",
            "content": f"Your goal is: {args.goal}\nWork towards this goal autonomously.",
        })
        agent.ollama._history.append({
            "role": "assistant",
            "content": '{"action": "wait", "value": 1}',
        })

    def signal_handler(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Start web server in background thread
    if not args.no_web:
        import asyncio

        loop_ready = threading.Event()

        def _run_uvicorn():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            agent._uvicorn_loop = loop
            loop_ready.set()
            uvicorn.run(
                web_app,
                host=WEB_HOST,
                port=args.port,
                log_level="warning",
                loop="asyncio",
            )

        server_thread = threading.Thread(target=_run_uvicorn, daemon=True)
        server_thread.start()
        loop_ready.wait(timeout=5)
        print(f"[Web UI] http://localhost:{args.port}")

    agent.start()
    agent.run_loop()


if __name__ == "__main__":
    main()
