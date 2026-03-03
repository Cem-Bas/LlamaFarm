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
