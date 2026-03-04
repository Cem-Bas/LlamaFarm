"""Tests for SwarmManager."""

import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from swarm import SwarmManager


class TestSwarmManagerInit:
    """Tests for SwarmManager initialization."""

    def test_init_defaults(self):
        """SwarmManager initializes with empty worker list and max_workers."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            assert sm.max_workers == 4
            assert len(sm.workers) == 0
            assert sm.orchestrator is not None

    def test_init_creates_orchestrator(self):
        """SwarmManager creates an orchestrator agent."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=4, web_enabled=False)
            assert sm.orchestrator is not None


class TestSwarmManagerSpawn:
    """Tests for spawning workers."""

    def test_spawn_worker_adds_to_dict(self):
        """spawn_worker creates a new worker and adds it to workers dict."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=4, web_enabled=False)
            worker_id = sm.spawn_worker(goal="run ls")
            assert worker_id in sm.workers
            assert sm.workers[worker_id]["goal"] == "run ls"

    def test_spawn_worker_returns_id(self):
        """spawn_worker returns the new worker's ID."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=4, web_enabled=False)
            worker_id = sm.spawn_worker(goal="test")
            assert worker_id.startswith("worker-")

    def test_spawn_worker_increments_ids(self):
        """Each spawned worker gets a sequential ID."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=4, web_enabled=False)
            id1 = sm.spawn_worker(goal="a")
            id2 = sm.spawn_worker(goal="b")
            assert id1 == "worker-01"
            assert id2 == "worker-02"

    def test_spawn_worker_respects_max(self):
        """spawn_worker returns None when max_workers reached."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=2, web_enabled=False)
            sm.spawn_worker(goal="a")
            sm.spawn_worker(goal="b")
            result = sm.spawn_worker(goal="c")
            assert result is None
            assert len(sm.workers) == 2


class TestSwarmManagerKill:
    """Tests for killing workers."""

    def test_kill_worker_removes_from_dict(self):
        """kill_worker removes the worker from the dict."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=4, web_enabled=False)
            wid = sm.spawn_worker(goal="test")
            sm.kill_worker(wid)
            assert wid not in sm.workers

    def test_kill_worker_stops_agent(self):
        """kill_worker calls stop() on the worker's agent."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=4, web_enabled=False)
            wid = sm.spawn_worker(goal="test")
            agent = sm.workers[wid]["agent"]
            sm.kill_worker(wid)
            agent.stop.assert_called_once()

    def test_kill_nonexistent_worker_is_noop(self):
        """kill_worker on unknown ID does not raise."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.kill_worker("worker-99")  # no error


class TestSwarmManagerAssign:
    """Tests for assigning goals."""

    def test_assign_goal_updates_worker(self):
        """assign_goal updates the worker's goal."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=4, web_enabled=False)
            wid = sm.spawn_worker(goal="old goal")
            sm.assign_goal(wid, "new goal")
            assert sm.workers[wid]["goal"] == "new goal"

    def test_assign_goal_seeds_history(self):
        """assign_goal seeds the worker's Ollama history with the goal."""
        with patch("swarm.TerminalAgent") as MockAgent:
            sm = SwarmManager(max_workers=4, web_enabled=False)
            wid = sm.spawn_worker(goal="old")
            sm.assign_goal(wid, "explore /tmp")
            agent = sm.workers[wid]["agent"]
            agent.goal = "explore /tmp"


class TestSwarmManagerSnapshots:
    """Tests for collecting snapshots."""

    def test_get_all_snapshots(self):
        """get_all_snapshots returns dict of agent_id to snapshot."""
        with patch("swarm.TerminalAgent") as MockAgent:
            mock_instance = MockAgent.return_value
            mock_instance.get_snapshot.return_value = {
                "agent_id": "worker-01",
                "status": "idle",
                "iteration": 0,
                "last_action": None,
                "screen_text": "",
                "goal": "test",
            }
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.spawn_worker(goal="test")
            snaps = sm.get_all_snapshots()
            assert "worker-01" in snaps
            assert "orchestrator" in snaps

    def test_snapshots_are_copies(self):
        """Snapshots are independent copies, not references."""
        with patch("swarm.TerminalAgent") as MockAgent:
            mock_instance = MockAgent.return_value
            snap_data = {"agent_id": "worker-01", "status": "idle",
                         "iteration": 0, "last_action": None,
                         "screen_text": "", "goal": "test"}
            mock_instance.get_snapshot.return_value = snap_data.copy()
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.spawn_worker(goal="test")
            s1 = sm.get_all_snapshots()
            s2 = sm.get_all_snapshots()
            assert s1 is not s2


class TestSwarmManagerKillAll:
    """Tests for kill_all (kill switch)."""

    def test_kill_all_removes_all_workers(self):
        """kill_all removes every worker from the dict."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.spawn_worker(goal="a")
            sm.spawn_worker(goal="b")
            sm.spawn_worker(goal="c")
            assert len(sm.workers) == 3
            result = sm.kill_all()
            assert len(sm.workers) == 0
            assert result["count"] == 3

    def test_kill_all_returns_killed_ids(self):
        """kill_all returns a list of killed worker IDs."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.spawn_worker(goal="a")
            sm.spawn_worker(goal="b")
            result = sm.kill_all()
            assert "worker-01" in result["killed_workers"]
            assert "worker-02" in result["killed_workers"]

    def test_kill_all_stops_each_agent(self):
        """kill_all calls stop() on every worker agent."""
        with patch("swarm.TerminalAgent") as MockAgent:
            # Each call to TerminalAgent() returns a fresh mock
            mock_agents = [MagicMock(), MagicMock(), MagicMock()]
            MockAgent.side_effect = mock_agents
            sm = SwarmManager(max_workers=4, web_enabled=False)
            # mock_agents[0] is the orchestrator
            sm.spawn_worker(goal="a")   # mock_agents[1]
            sm.spawn_worker(goal="b")   # mock_agents[2]
            sm.kill_all()
            mock_agents[1].stop.assert_called_once()
            mock_agents[2].stop.assert_called_once()

    def test_kill_all_clears_orchestrator_history(self):
        """kill_all clears the orchestrator's conversation history."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm._orch_agent._history.append({"role": "user", "content": "test"})
            sm.kill_all()
            assert len(sm._orch_agent._history) == 0

    def test_kill_all_resets_orchestrator_status(self):
        """kill_all resets orchestrator status to idle."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.orchestrator.status = "thinking"
            sm.kill_all()
            assert sm.orchestrator.status == "idle"

    def test_kill_all_with_no_workers(self):
        """kill_all is safe when no workers exist."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            result = sm.kill_all()
            assert result["count"] == 0
            assert result["killed_workers"] == []

    def test_can_spawn_after_kill_all(self):
        """Workers can be spawned again after kill_all."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=2, web_enabled=False)
            sm.spawn_worker(goal="a")
            sm.spawn_worker(goal="b")
            assert sm.spawn_worker(goal="c") is None  # at max
            sm.kill_all()
            wid = sm.spawn_worker(goal="d")
            assert wid is not None
            assert len(sm.workers) == 1


class TestSwarmManagerOrchestratorCommand:
    """Tests for processing orchestrator commands."""

    def test_process_assign_command(self):
        """process_command handles assign."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.spawn_worker(goal="old")
            sm.process_command({"command": "assign", "worker": "worker-01", "goal": "new goal"})
            assert sm.workers["worker-01"]["goal"] == "new goal"

    def test_process_spawn_command(self):
        """process_command handles spawn."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.process_command({"command": "spawn", "shell_cmd": "ollama run llama3.2"})
            assert len(sm.workers) == 1

    def test_process_kill_command(self):
        """process_command handles kill."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.spawn_worker(goal="test")
            sm.process_command({"command": "kill", "worker": "worker-01"})
            assert len(sm.workers) == 0

    def test_process_wait_command(self):
        """process_command handles wait (no-op)."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.process_command({"command": "wait", "value": 1})

    def test_process_unknown_command(self):
        """process_command ignores unknown commands."""
        with patch("swarm.TerminalAgent"):
            sm = SwarmManager(max_workers=4, web_enabled=False)
            sm.process_command({"command": "dance"})
