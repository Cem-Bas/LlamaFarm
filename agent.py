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
)
from keystroke_engine import encode_action
from ollama_client import OllamaAgent
from pty_manager import PTYManager
from screen import TerminalScreen
from web.server import broadcast as web_broadcast, app as web_app


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
    """

    def __init__(
        self,
        model: str = MODEL,
        cols: int = SCREEN_COLS,
        rows: int = SCREEN_ROWS,
        shell: str = SHELL,
        max_history: int = MAX_HISTORY,
        web_enabled: bool = True,
    ) -> None:
        self.pty = PTYManager(shell=shell, cols=cols, rows=rows)
        self.screen = TerminalScreen(cols=cols, rows=rows)
        self.ollama = OllamaAgent(model=model, max_history=max_history)
        self.web_enabled = web_enabled
        self.running = False
        self.iteration = 0
        self.last_action: dict | None = None

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
        """
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
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    web_broadcast(data.get("screen_text", ""), data.get("action", {}), data.get("iteration", 0))
                )
        except RuntimeError:
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
                action = self.think(screen_text)
                print(f"[Action] {json.dumps(action)}")

                # --- Broadcast ---
                self._broadcast("action", {
                    "screen_text": screen_text,
                    "iteration": self.iteration,
                    "action": action,
                })

                # --- Act ---
                self.act(action)

            except KeyboardInterrupt:
                print("\n[Agent] Interrupted.")
                break
            except Exception as e:
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

    parser = argparse.ArgumentParser(description="Ollama Terminal Agent")
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
        server_thread = threading.Thread(
            target=uvicorn.run,
            args=(web_app,),
            kwargs={"host": WEB_HOST, "port": args.port, "log_level": "warning"},
            daemon=True,
        )
        server_thread.start()
        print(f"[Web UI] http://localhost:{args.port}")

    agent.start()
    agent.run_loop()


if __name__ == "__main__":
    main()
