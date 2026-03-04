"""Agent Swarm — multi-agent orchestration system.

Coordinates up to 8 WorkerAgents under one OrchestratorAgent.
Each worker runs a TerminalAgent in its own thread with its own PTY.

Exports
-------
SwarmManager — the main swarm coordinator class.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Optional

from agent import TerminalAgent
from cli_agent import TerminalCLIAgent
from config import (
    MAX_WORKERS,
    ORCHESTRATOR_MODEL,
    WORKER_MODEL,
    SCREEN_COLS,
    SCREEN_ROWS,
    SHELL,
    MAX_HISTORY,
    SWARM_BROADCAST_INTERVAL,
    is_cli_agent,
)


class SwarmManager:
    """Manages a swarm of worker agents under one orchestrator.

    Parameters
    ----------
    max_workers : int
        Maximum number of concurrent worker agents.
    orchestrator_model : str
        Ollama model for the orchestrator.
    worker_model : str
        Ollama model for worker agents.
    web_enabled : bool
        Whether web broadcasting is active.
    """

    def __init__(
        self,
        max_workers: int = MAX_WORKERS,
        orchestrator_model: str = ORCHESTRATOR_MODEL,
        worker_model: str = WORKER_MODEL,
        web_enabled: bool = True,
    ) -> None:
        self.max_workers = max_workers
        self.orchestrator_model = orchestrator_model
        self.worker_model = worker_model
        self.web_enabled = web_enabled
        self.workers: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._worker_counter = 0
        self._worker_threads: dict[str, threading.Thread] = {}
        self._pending_messages: list[str] = []  # user messages queued for next tick

        # Create orchestrator agent
        self.orchestrator = TerminalAgent(
            model=orchestrator_model,
            agent_id="orchestrator",
            goal="",
            web_enabled=False,
        )

        # Create the orchestrator decision engine
        if is_cli_agent(orchestrator_model):
            cli_name = orchestrator_model.replace("-cli", "")
            self._orch_agent = TerminalCLIAgent(
                cli_name=cli_name,
                orchestrator=True,
            )
        else:
            from ollama_client import OllamaAgent
            self._orch_agent = OllamaAgent(
                model=orchestrator_model,
                orchestrator=True,
            )

    def spawn_worker(self, goal: str = "", shell_cmd: str = "", model: str = "") -> Optional[str]:
        """Spawn a new worker agent. Returns worker_id or None if at max.

        Parameters
        ----------
        model : str
            If provided, overrides ``self.worker_model`` for this worker.
        """
        with self._lock:
            if len(self.workers) >= self.max_workers:
                return None
            self._worker_counter += 1
            worker_id = f"llama-{self._worker_counter:02d}"

        use_model = model if model else self.worker_model
        agent = TerminalAgent(
            model=use_model,
            agent_id=worker_id,
            goal=goal,
            web_enabled=False,
        )

        with self._lock:
            self.workers[worker_id] = {
                "agent": agent,
                "goal": goal,
                "shell_cmd": shell_cmd,
                "thread": None,
                "spawn_time": time.time(),
            }

        return worker_id

    def kill_worker(self, worker_id: str) -> None:
        """Stop and remove a worker by ID."""
        with self._lock:
            worker = self.workers.pop(worker_id, None)
        if worker is not None:
            worker["agent"].stop()

    def kill_all(self) -> dict:
        """Kill switch — stop ALL workers and pause the orchestrator.

        Returns a summary dict with counts of what was killed.
        """
        with self._lock:
            worker_ids = list(self.workers.keys())
        killed = []
        for wid in worker_ids:
            self.kill_worker(wid)
            killed.append(wid)
        # Clear orchestrator history so it starts fresh
        self._orch_agent._history.clear()
        self.orchestrator.status = "idle"
        self.orchestrator.iteration = 0
        return {
            "killed_workers": killed,
            "count": len(killed),
        }

    def queue_message(self, message: str) -> None:
        """Queue a user message for the orchestrator's next tick."""
        with self._lock:
            self._pending_messages.append(message)

    def assign_goal(self, worker_id: str, goal: str) -> None:
        """Assign a new goal to an existing worker."""
        with self._lock:
            if worker_id not in self.workers:
                return
            self.workers[worker_id]["goal"] = goal
            agent = self.workers[worker_id]["agent"]
        agent.goal = goal
        if hasattr(agent, 'ollama'):
            agent.ollama.goal = goal

    def get_all_snapshots(self) -> dict:
        """Collect snapshots from all agents (orchestrator + workers)."""
        snapshots = {}
        # Orchestrator snapshot — build a useful one from the decision engine
        snap = self.orchestrator.get_snapshot()
        snap["model"] = self._orch_agent.model
        if self.orchestrator.last_action:
            snap["screen_text"] = json.dumps(self.orchestrator.last_action)
        snapshots["orchestrator"] = snap
        # Worker snapshots
        with self._lock:
            worker_items = list(self.workers.items())
        for worker_id, worker in worker_items:
            snapshots[worker_id] = worker["agent"].get_snapshot()
        return snapshots

    def process_command(self, command: dict) -> None:
        """Process a command from the orchestrator."""
        cmd = command.get("command", "")
        if cmd == "assign":
            self.assign_goal(command.get("worker", ""), command.get("goal", ""))
        elif cmd == "spawn":
            self.spawn_worker(
                goal=command.get("goal", ""),
                shell_cmd=command.get("shell_cmd", ""),
            )
        elif cmd == "kill":
            self.kill_worker(command.get("worker", ""))
        elif cmd == "wait":
            pass  # No-op — orchestrator is waiting
        elif cmd == "reply":
            pass  # Reply-only — handled by the web layer
        # Unknown commands are silently ignored

    def build_orchestrator_input(self) -> str:
        """Format all worker snapshots into a compact text summary for the orchestrator."""
        snapshots = self.get_all_snapshots()
        lines = ["SWARM STATUS:"]

        # Include goal if set
        if self.orchestrator.goal:
            lines.append(f"MISSION: {self.orchestrator.goal}")

        n_workers = len(snapshots) - 1  # exclude orchestrator
        lines.append(f"Workers: {n_workers}/{self.max_workers}")
        lines.append("")

        for agent_id, snap in snapshots.items():
            if agent_id == "orchestrator":
                continue
            status = snap.get("status", "unknown")
            goal = snap.get("goal", "none")
            screen = snap.get("screen_text", "").strip()
            last_3 = "\n".join(screen.split("\n")[-3:]) if screen else "(empty)"
            # Show age so orchestrator knows new workers need time
            with self._lock:
                worker_data = self.workers.get(agent_id, {})
            spawn_time = worker_data.get("spawn_time", 0)
            age_secs = int(time.time() - spawn_time) if spawn_time else 0
            lines.append(f"[{agent_id}] status={status} goal={goal} age={age_secs}s")
            lines.append(f"  screen: {last_3}")
            lines.append("")

        if n_workers == 0 and self.orchestrator.goal:
            lines.append("No workers yet. Spawn one to accomplish the mission.")
        elif n_workers == 0:
            lines.append("No mission set. Wait for user instructions.")
        else:
            # Check if any workers are actively working
            busy = [aid for aid, s in snapshots.items()
                    if aid != "orchestrator" and s.get("status") in ("acting", "thinking")]
            if busy:
                lines.append(f"WORKERS BUSY: {', '.join(busy)}. You MUST use wait.")

        # Show last command so orchestrator doesn't repeat itself
        if self.orchestrator.last_action:
            lines.append(f"YOUR LAST COMMAND: {json.dumps(self.orchestrator.last_action)}")
            lines.append("Do NOT repeat the same command.")

        # Include any pending user messages
        with self._lock:
            messages = list(self._pending_messages)
            self._pending_messages.clear()
        if messages:
            lines.append("")
            lines.append("USER MESSAGES:")
            for msg in messages:
                lines.append(f"  > {msg}")

        lines.append("")
        lines.append("Reply with ONE JSON command.")
        return "\n".join(lines)

    def tick_orchestrator(self) -> dict:
        """Run one orchestrator decision cycle. Returns the command dict."""
        # No mission and no pending user messages → skip entirely, just wait
        has_messages = bool(self._pending_messages)
        if not self.orchestrator.goal and not has_messages and not self.workers:
            self.orchestrator.status = "idle"
            return {"command": "wait", "value": 2}

        self.orchestrator.status = "thinking"
        self.orchestrator.iteration += 1
        input_text = self.build_orchestrator_input()
        command = self._orch_agent.decide(input_text)

        # Block spawn if no mission and no user instruction
        cmd = command.get("command", "")
        if cmd == "spawn" and not self.orchestrator.goal and not has_messages:
            print("[Swarm] BLOCKED: no mission set, not spawning")
            command = {"command": "wait", "value": 2}

        # Dedup: if workers exist and model wants to spawn the same goal again, force wait
        if cmd == "spawn" and self.workers:
            new_goal = command.get("goal", "").lower().strip()
            with self._lock:
                existing_goals = [w["goal"].lower().strip() for w in self.workers.values()]
            if new_goal and any(new_goal in g or g in new_goal for g in existing_goals):
                print(f"[Swarm] DEDUP: blocked duplicate spawn for '{command.get('goal', '')}'")
                command = {"command": "wait", "value": 3}

        self.orchestrator.status = "acting"
        self.orchestrator.last_action = command
        self.process_command(command)
        self.orchestrator.status = "idle"
        return command

    def start(self) -> None:
        """Start the orchestrator agent."""
        self.orchestrator.start()

    def stop(self) -> None:
        """Stop all agents."""
        with self._lock:
            worker_ids = list(self.workers.keys())
        for wid in worker_ids:
            self.kill_worker(wid)
        self.orchestrator.stop()
        # Close CLI orchestrator PTY if applicable
        if hasattr(self._orch_agent, 'close'):
            self._orch_agent.close()

    def _start_worker_thread(self, worker_id: str) -> None:
        """Start a worker in a background thread.

        CLI agents (codex-cli, claude-cli, gemini-cli): runs the CLI tool
        directly in the worker PTY. The CLI handles command execution
        autonomously. Worker loop just observes for status reporting.

        Ollama agents: uses the original observe-think-act loop where the
        Ollama model decides actions and the agent types them into the shell.
        """
        with self._lock:
            if worker_id not in self.workers:
                return
            agent = self.workers[worker_id]["agent"]
            goal = self.workers[worker_id].get("goal", "")
            shell_cmd = self.workers[worker_id].get("shell_cmd", "")

        def _run_cli():
            """CLI agent path — run the CLI tool in the PTY."""
            try:
                agent.start()
                time.sleep(0.5)

                # Build prompt from goal and/or shell_cmd
                if goal and shell_cmd:
                    cli_prompt = f"{goal}. Start by running: {shell_cmd}"
                elif goal:
                    cli_prompt = goal
                elif shell_cmd:
                    cli_prompt = f"Run this command: {shell_cmd}"
                else:
                    cli_prompt = "Await instructions"

                # Determine which CLI to launch
                cli_name = agent.ollama.cli_name if hasattr(agent.ollama, 'cli_name') else "codex"
                safe_prompt = cli_prompt.replace("'", "'\\''")

                if cli_name == "codex":
                    cli_cmd = f"codex --dangerously-skip-permissions '{safe_prompt}'\n"
                elif cli_name == "claude":
                    # Use -p (print) mode for non-interactive execution
                    cli_cmd = f"claude -p --dangerously-skip-permissions '{safe_prompt}'\n"
                elif cli_name == "gemini":
                    cli_cmd = f"gemini '{safe_prompt}'\n"
                else:
                    cli_cmd = f"{cli_name} '{safe_prompt}'\n"

                agent.pty.write(cli_cmd.encode())
                agent.status = "acting"

                # Observe loop — read screen for status reporting
                # Also auto-handle any remaining CLI prompts
                accepted = False
                while agent.running and agent.pty.is_alive():
                    data = agent.pty.read(timeout=0.5)
                    if data:
                        agent.screen.feed(data)
                        agent.iteration += 1

                        # Check full screen buffer for prompts (not just current chunk)
                        if not accepted:
                            screen_text = "\n".join(
                                agent.screen._screen.display[row]
                                for row in range(agent.screen._screen.lines)
                            )
                            # Auto-answer acceptance dialogs by sending the number
                            if "Yes, I accept" in screen_text:
                                time.sleep(0.5)
                                agent.pty.write(b"2\r")  # send "2" for Yes option
                                accepted = True
                            elif "trust this project" in screen_text.lower():
                                time.sleep(0.5)
                                agent.pty.write(b"1\r")  # trust project
                                accepted = True
                    time.sleep(0.2)

            except Exception as e:
                print(f"[Worker {worker_id}] Error: {e}")
                agent.status = "error"

        def _run_ollama():
            """Ollama agent path — runs worker_agent.py inside the PTY."""
            try:
                agent.start()
                time.sleep(0.5)

                # Build the goal from goal and/or shell_cmd
                if goal and shell_cmd:
                    agent_goal = f"{goal}. Start by running: {shell_cmd}"
                elif goal:
                    agent_goal = goal
                elif shell_cmd:
                    agent_goal = f"Run this command: {shell_cmd}"
                else:
                    agent_goal = "Await instructions"

                # Launch the Ollama worker agent inside the PTY
                model = agent.ollama.model
                safe_goal = agent_goal.replace("'", "'\\''")
                cmd = f"python worker_agent.py --model '{model}' --goal '{safe_goal}'\n"
                agent.pty.write(cmd.encode())
                agent.status = "acting"

                # Observe loop — read the screen for status reporting
                while agent.running and agent.pty.is_alive():
                    data = agent.pty.read(timeout=0.5)
                    if data:
                        agent.screen.feed(data)
                        agent.iteration += 1
                    time.sleep(0.2)

            except Exception as e:
                print(f"[Worker {worker_id}] Error: {e}")
                agent.status = "error"

        target = _run_cli if agent._is_cli else _run_ollama
        thread = threading.Thread(target=target, daemon=True, name=f"swarm-{worker_id}")
        with self._lock:
            if worker_id in self.workers:
                self.workers[worker_id]["thread"] = thread
        thread.start()
        self._worker_threads[worker_id] = thread


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def swarm_main() -> None:
    import argparse
    import asyncio
    import signal
    import sys
    import threading
    import uvicorn

    from config import WEB_HOST, WEB_PORT, SWARM_BROADCAST_INTERVAL
    from web.server import (
        app as web_app,
        broadcast_swarm_state,
        broadcast_swarm_event,
        set_swarm_manager,
        get_uvicorn_loop,
    )

    parser = argparse.ArgumentParser(description="Clawllama Swarm")
    parser.add_argument("--orchestrator-model", default=ORCHESTRATOR_MODEL,
                        help="Ollama model for the orchestrator")
    parser.add_argument("--worker-model", default=WORKER_MODEL,
                        help="Ollama model for workers")
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS,
                        help="Max concurrent workers")
    parser.add_argument("--port", type=int, default=WEB_PORT,
                        help="Web UI port")
    parser.add_argument("--goal", default=None,
                        help="Initial goal for the orchestrator")
    args = parser.parse_args()

    manager = SwarmManager(
        max_workers=args.max_workers,
        orchestrator_model=args.orchestrator_model,
        worker_model=args.worker_model,
    )

    # Register manager with web layer so UI commands can reach it
    set_swarm_manager(manager)

    # Set the mission goal on both the orchestrator agent and the CLI agent
    if args.goal:
        manager.orchestrator.goal = args.goal
        manager._orch_agent.goal = args.goal

    def signal_handler(sig, frame):
        print("\n[Swarm] Shutting down...")
        manager.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Start web server in background thread
    server_ready = threading.Event()

    def _run_uvicorn():
        uvicorn.run(
            web_app,
            host=WEB_HOST,
            port=args.port,
            log_level="warning",
        )

    server_thread = threading.Thread(target=_run_uvicorn, daemon=True)
    server_thread.start()

    # Wait for uvicorn to start and capture its real event loop
    for _ in range(50):
        time.sleep(0.1)
        if get_uvicorn_loop() is not None:
            break
    print(f"[Swarm] Web UI: http://localhost:{args.port}/swarm")

    # Main swarm loop
    print(f"[Swarm] Orchestrator model: {manager.orchestrator_model}")
    print(f"[Swarm] Worker model: {manager.worker_model}")
    print(f"[Swarm] Max workers: {manager.max_workers}")
    print(f"[Swarm] Starting orchestrator loop...")

    tick = 0
    while True:
        try:
            tick += 1

            # Tick orchestrator
            command = manager.tick_orchestrator()
            print(f"[Swarm] Tick {tick}: {json.dumps(command)}")

            # Broadcast swarm state
            snapshots = manager.get_all_snapshots()
            print(f"[Swarm] Snapshot keys: {list(snapshots.keys())} workers: {list(manager.workers.keys())}")
            loop = get_uvicorn_loop()
            if loop is not None and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    broadcast_swarm_state(snapshots, tick=tick), loop
                )
                # Check broadcast result for errors
                try:
                    fut.result(timeout=2)
                except Exception as e:
                    print(f"[Swarm] broadcast error: {e}")

                # Broadcast events for spawns/kills
                cmd = command.get("command", "")
                if cmd == "spawn":
                    # Find the latest worker
                    worker_ids = list(manager.workers.keys())
                    if worker_ids:
                        latest = worker_ids[-1]
                        asyncio.run_coroutine_threadsafe(
                            broadcast_swarm_event(
                                "worker_spawned", latest,
                                command.get("shell_cmd", "")
                            ),
                            loop,
                        )
                        # Start the worker's run loop
                        manager._start_worker_thread(latest)
                elif cmd == "kill":
                    asyncio.run_coroutine_threadsafe(
                        broadcast_swarm_event(
                            "worker_killed", command.get("worker", ""), ""
                        ),
                        loop,
                    )

            time.sleep(SWARM_BROADCAST_INTERVAL)

        except KeyboardInterrupt:
            print("\n[Swarm] Interrupted.")
            break
        except Exception as e:
            print(f"\n[Swarm] Error: {e}")
            time.sleep(1)

    manager.stop()
    print("[Swarm] Stopped.")


if __name__ == "__main__":
    swarm_main()
