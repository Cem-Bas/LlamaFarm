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
from config import (
    MAX_WORKERS,
    ORCHESTRATOR_MODEL,
    WORKER_MODEL,
    SCREEN_COLS,
    SCREEN_ROWS,
    SHELL,
    MAX_HISTORY,
    SWARM_BROADCAST_INTERVAL,
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

        # Create orchestrator agent
        self.orchestrator = TerminalAgent(
            model=orchestrator_model,
            agent_id="orchestrator",
            goal="Coordinate workers",
            web_enabled=False,
        )
        # Set the orchestrator's OllamaAgent to use orchestrator mode
        self.orchestrator.ollama.orchestrator = True

    def spawn_worker(self, goal: str = "", shell_cmd: str = "") -> Optional[str]:
        """Spawn a new worker agent. Returns worker_id or None if at max."""
        with self._lock:
            if len(self.workers) >= self.max_workers:
                return None
            self._worker_counter += 1
            worker_id = f"worker-{self._worker_counter:02d}"

        agent = TerminalAgent(
            model=self.worker_model,
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
            }

        return worker_id

    def kill_worker(self, worker_id: str) -> None:
        """Stop and remove a worker by ID."""
        with self._lock:
            worker = self.workers.pop(worker_id, None)
        if worker is not None:
            worker["agent"].stop()

    def assign_goal(self, worker_id: str, goal: str) -> None:
        """Assign a new goal to an existing worker."""
        with self._lock:
            if worker_id not in self.workers:
                return
            self.workers[worker_id]["goal"] = goal
            agent = self.workers[worker_id]["agent"]
        agent.goal = goal
        # Seed the worker's Ollama history with the new goal
        agent.ollama._history.append({
            "role": "user",
            "content": f"Your goal is: {goal}\nWork towards this goal autonomously.",
        })
        agent.ollama._history.append({
            "role": "assistant",
            "content": '{"action": "wait", "value": 1}',
        })

    def get_all_snapshots(self) -> dict:
        """Collect snapshots from all agents (orchestrator + workers)."""
        snapshots = {}
        # Orchestrator snapshot
        snapshots["orchestrator"] = self.orchestrator.get_snapshot()
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
        # Unknown commands are silently ignored

    def build_orchestrator_input(self) -> str:
        """Format all worker snapshots into a text summary for the orchestrator."""
        snapshots = self.get_all_snapshots()
        lines = ["=== SWARM STATUS ===", ""]
        for agent_id, snap in snapshots.items():
            if agent_id == "orchestrator":
                continue
            lines.append(f"Worker: {agent_id}")
            lines.append(f"  Status: {snap.get('status', 'unknown')}")
            lines.append(f"  Goal: {snap.get('goal', 'none')}")
            lines.append(f"  Iteration: {snap.get('iteration', 0)}")
            action = snap.get("last_action")
            lines.append(f"  Last Action: {json.dumps(action) if action else 'none'}")
            lines.append(f"  Screen (last 5 lines):")
            screen = snap.get("screen_text", "")
            if screen:
                for line in screen.split("\n"):
                    lines.append(f"    {line}")
            else:
                lines.append("    (empty)")
            lines.append("")
        if len(snapshots) <= 1:
            lines.append("No workers active. Use spawn to create one.")
            lines.append("")
        lines.append(f"Active workers: {len(snapshots) - 1}/{self.max_workers}")
        return "\n".join(lines)

    def tick_orchestrator(self) -> dict:
        """Run one orchestrator decision cycle. Returns the command dict."""
        input_text = self.build_orchestrator_input()
        command = self.orchestrator.ollama.decide(input_text)
        self.process_command(command)
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

    def _start_worker_thread(self, worker_id: str) -> None:
        """Start a worker's run_loop in a background thread."""
        with self._lock:
            if worker_id not in self.workers:
                return
            agent = self.workers[worker_id]["agent"]

        def _run():
            try:
                agent.start()
                agent.run_loop()
            except Exception:
                agent.status = "error"

        thread = threading.Thread(target=_run, daemon=True, name=f"swarm-{worker_id}")
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

    # Seed orchestrator with initial goal
    if args.goal:
        manager.orchestrator.ollama._history.append({
            "role": "user",
            "content": f"Your goal is: {args.goal}\nYou have {args.max_workers} worker slots. Decide what to do.",
        })
        manager.orchestrator.ollama._history.append({
            "role": "assistant",
            "content": '{"command": "wait", "value": 2}',
        })

    def signal_handler(sig, frame):
        print("\n[Swarm] Shutting down...")
        manager.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Start web server in background thread
    loop_ready = threading.Event()
    uvicorn_loop = None

    def _run_uvicorn():
        nonlocal uvicorn_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        uvicorn_loop = loop
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
            if uvicorn_loop and uvicorn_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    broadcast_swarm_state(snapshots), uvicorn_loop
                )

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
                            uvicorn_loop,
                        )
                        # Start the worker's run loop
                        manager._start_worker_thread(latest)
                elif cmd == "kill":
                    asyncio.run_coroutine_threadsafe(
                        broadcast_swarm_event(
                            "worker_killed", command.get("worker", ""), ""
                        ),
                        uvicorn_loop,
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
