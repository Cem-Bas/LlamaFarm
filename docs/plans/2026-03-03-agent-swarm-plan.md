# Agent Swarm with Cyberpunk UI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the single-agent terminal controller into a multi-agent swarm with orchestrator pattern and cyberpunk-themed web dashboard.

**Architecture:** SwarmManager coordinates up to 8 WorkerAgents + 1 OrchestratorAgent, each running a TerminalAgent in its own thread. A multiplexed WebSocket broadcasts all agent states to a cyberpunk web UI with xterm.js terminals, matrix rain, neon glows, and particle data flow lines.

**Tech Stack:** Python 3.11+, FastAPI, pyte, ptyprocess, ollama SDK, xterm.js 5.5.0, HTML5 Canvas

---

### Task 1: Add `get_snapshot()` to TerminalAgent

Extend the existing `TerminalAgent` class with a thread-safe snapshot method that returns current state as a dict. This is the foundation for the swarm — the manager and orchestrator read agent state through snapshots.

**Files:**
- Modify: `agent.py`
- Modify: `tests/test_agent.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent.py`:

```python
# --- Snapshot tests ---

class TestGetSnapshot:
    """Tests for TerminalAgent.get_snapshot()."""

    def test_snapshot_returns_dict(self, agent):
        """get_snapshot returns a dict with required keys."""
        snap = agent.get_snapshot()
        assert isinstance(snap, dict)
        assert "agent_id" in snap
        assert "status" in snap
        assert "iteration" in snap
        assert "last_action" in snap
        assert "screen_text" in snap
        assert "goal" in snap

    def test_snapshot_default_values(self, agent):
        """Snapshot has correct defaults before any loop runs."""
        snap = agent.get_snapshot()
        assert snap["status"] == "idle"
        assert snap["iteration"] == 0
        assert snap["last_action"] is None
        assert snap["goal"] == ""

    def test_snapshot_reflects_agent_id(self):
        """Snapshot includes the agent_id set at construction."""
        with patch("agent.PTYManager"):
            with patch("agent.OllamaAgent"):
                a = TerminalAgent(agent_id="worker-03", web_enabled=False)
                snap = a.get_snapshot()
                assert snap["agent_id"] == "worker-03"

    def test_snapshot_reflects_iteration(self, agent):
        """Snapshot reflects current iteration count."""
        agent.iteration = 7
        snap = agent.get_snapshot()
        assert snap["iteration"] == 7

    def test_snapshot_reflects_last_action(self, agent):
        """Snapshot reflects last_action."""
        agent.last_action = {"action": "type", "value": "ls"}
        snap = agent.get_snapshot()
        assert snap["last_action"] == {"action": "type", "value": "ls"}

    def test_snapshot_reflects_goal(self):
        """Snapshot reflects goal set at construction."""
        with patch("agent.PTYManager"):
            with patch("agent.OllamaAgent"):
                a = TerminalAgent(agent_id="w1", goal="explore files", web_enabled=False)
                snap = a.get_snapshot()
                assert snap["goal"] == "explore files"

    def test_snapshot_screen_text_snippet(self, agent):
        """screen_text in snapshot is last 5 lines of screen."""
        agent.screen.feed(b"line1\r\nline2\r\nline3\r\nline4\r\nline5\r\nline6\r\nline7\r\n")
        snap = agent.get_snapshot()
        # Should contain the last 5 non-empty lines
        lines = [l for l in snap["screen_text"].split("\n") if l.strip()]
        assert len(lines) <= 5

    def test_snapshot_includes_status_field(self, agent):
        """Status transitions are reflected in snapshot."""
        agent.status = "thinking"
        snap = agent.get_snapshot()
        assert snap["status"] == "thinking"
```

Add required import at top of test file:
```python
from unittest.mock import patch
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent.py::TestGetSnapshot -v`
Expected: FAIL — `TerminalAgent` has no `get_snapshot` method, no `agent_id` param, no `goal` param, no `status` attribute

**Step 3: Implement get_snapshot and new constructor params**

In `agent.py`, modify `TerminalAgent.__init__` to accept `agent_id` and `goal`:

```python
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
    self.pty = PTYManager(shell=shell, cols=cols, rows=rows)
    self.screen = TerminalScreen(cols=cols, rows=rows)
    self.ollama = OllamaAgent(model=model, max_history=max_history)
    self.web_enabled = web_enabled
    self.running = False
    self.iteration = 0
    self.last_action: dict | None = None
    self.status: str = "idle"
    self._uvicorn_loop = None
```

Add the `get_snapshot` method after `stop()`:

```python
def get_snapshot(self) -> dict:
    """Return a read-only snapshot of this agent's current state."""
    screen_text = self.screen.get_text()
    # Last 5 non-empty lines as a compact summary
    lines = [l for l in screen_text.split("\n") if l.strip()]
    snippet = "\n".join(lines[-5:])
    return {
        "agent_id": self.agent_id,
        "status": self.status,
        "iteration": self.iteration,
        "last_action": self.last_action,
        "screen_text": snippet,
        "goal": self.goal,
    }
```

Update `run_loop` to set `self.status` at each phase:

In the loop body, before `action = self.think(screen_text)` add: `self.status = "thinking"`
After think, before `self.act(action)` add: `self.status = "acting"`
After act: `self.status = "idle"`
In exception handler: `self.status = "error"`

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent.py -v`
Expected: ALL PASS (existing + new)

**Step 5: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "feat: add get_snapshot(), agent_id, goal, status to TerminalAgent"
```

---

### Task 2: Add Swarm Config Defaults

Add swarm-related configuration to `config.py`.

**Files:**
- Modify: `config.py`

**Step 1: Add swarm config values**

Append to `config.py`:

```python
# Swarm settings
MAX_WORKERS = 8
SWARM_BROADCAST_INTERVAL = 0.5  # seconds between UI broadcasts
ORCHESTRATOR_MODEL = "devstral-small-2"  # model for the orchestrator
WORKER_MODEL = "devstral-small-2"  # model for worker agents
```

**Step 2: Commit**

```bash
git add config.py
git commit -m "feat: add swarm configuration defaults"
```

---

### Task 3: Orchestrator System Prompt

Add a second system prompt to `ollama_client.py` for the orchestrator role. The orchestrator receives worker summaries and returns swarm commands.

**Files:**
- Modify: `ollama_client.py`
- Modify: `tests/test_ollama_client.py`

**Step 1: Write the failing tests**

Add to `tests/test_ollama_client.py`:

```python
from ollama_client import ORCHESTRATOR_SYSTEM_PROMPT, OllamaAgent

class TestOrchestratorPrompt:
    """Tests for orchestrator system prompt and command parsing."""

    def test_orchestrator_prompt_exists(self):
        """ORCHESTRATOR_SYSTEM_PROMPT is a non-empty string."""
        assert isinstance(ORCHESTRATOR_SYSTEM_PROMPT, str)
        assert len(ORCHESTRATOR_SYSTEM_PROMPT) > 100

    def test_orchestrator_prompt_mentions_commands(self):
        """Prompt describes assign, spawn, kill, wait commands."""
        for cmd in ["assign", "spawn", "kill", "wait"]:
            assert cmd in ORCHESTRATOR_SYSTEM_PROMPT

    def test_agent_uses_orchestrator_prompt(self):
        """OllamaAgent with orchestrator=True uses ORCHESTRATOR_SYSTEM_PROMPT."""
        agent = OllamaAgent(model="test", orchestrator=True)
        messages = agent._build_messages("test screen")
        assert messages[0]["content"] == ORCHESTRATOR_SYSTEM_PROMPT

    def test_agent_default_uses_regular_prompt(self):
        """OllamaAgent without orchestrator flag uses regular SYSTEM_PROMPT."""
        agent = OllamaAgent(model="test", orchestrator=False)
        messages = agent._build_messages("test screen")
        assert "autonomous terminal agent" in messages[0]["content"].lower()

    def test_parse_orchestrator_assign_command(self):
        """Orchestrator assign command is valid JSON."""
        import json
        cmd = '{"command": "assign", "worker": "worker-01", "goal": "run ls"}'
        parsed = json.loads(cmd)
        assert parsed["command"] == "assign"
        assert parsed["worker"] == "worker-01"

    def test_parse_orchestrator_spawn_command(self):
        """Orchestrator spawn command is valid JSON."""
        import json
        cmd = '{"command": "spawn", "shell_cmd": "ollama run llama3.2"}'
        parsed = json.loads(cmd)
        assert parsed["command"] == "spawn"

    def test_parse_orchestrator_kill_command(self):
        """Orchestrator kill command is valid JSON."""
        import json
        cmd = '{"command": "kill", "worker": "worker-02"}'
        parsed = json.loads(cmd)
        assert parsed["command"] == "kill"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ollama_client.py::TestOrchestratorPrompt -v`
Expected: FAIL — `ORCHESTRATOR_SYSTEM_PROMPT` does not exist, `orchestrator` param not accepted

**Step 3: Implement**

Add to `ollama_client.py` after `SYSTEM_PROMPT`:

```python
ORCHESTRATOR_SYSTEM_PROMPT = """\
You are a swarm orchestrator agent. You manage a team of worker agents, each \
running in their own terminal. You read their status summaries and decide what \
to do next. You MUST respond with ONLY a single JSON object — no markdown, \
no explanation, no extra text.

Your response must be one of these command formats:

1. Assign a goal to a worker:
   {"command": "assign", "worker": "<worker-id>", "goal": "<what the worker should do>"}

2. Spawn a new worker:
   {"command": "spawn", "shell_cmd": "<initial command to run in the new terminal>"}

3. Kill a worker:
   {"command": "kill", "worker": "<worker-id>"}

4. Wait and observe:
   {"command": "wait", "value": <seconds>}

Worker summary format you receive:
- worker-id: status (idle|thinking|acting|error), goal, last action, last 5 lines of screen

Rules:
- Always respond with valid JSON only.
- Assign goals that involve running CLI tools like: ollama run <model>, gemini, codex, claude
- Workers can type commands, press keys, and interact with any terminal program.
- Use spawn to create new workers when you need more parallelism.
- Use kill to clean up workers that are done or stuck.
- Use wait when workers are busy and you need to observe progress.
- If you have no workers, spawn one first.\
"""
```

Modify `OllamaAgent.__init__` to accept `orchestrator` param:

```python
def __init__(self, model: str, max_history: int = 20, orchestrator: bool = False) -> None:
    self.model = model
    self.max_history = max_history
    self.orchestrator = orchestrator
    self._history: list[dict[str, str]] = []
```

Modify `_build_messages` to use the right prompt:

```python
def _build_messages(self, screen_text: str) -> list[dict[str, str]]:
    prompt = ORCHESTRATOR_SYSTEM_PROMPT if self.orchestrator else SYSTEM_PROMPT
    messages: list[dict[str, str]] = [
        {"role": "system", "content": prompt},
    ]
    messages.extend(self._history)
    messages.append({"role": "user", "content": screen_text})
    return messages
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ollama_client.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add ollama_client.py tests/test_ollama_client.py
git commit -m "feat: add ORCHESTRATOR_SYSTEM_PROMPT and orchestrator mode to OllamaAgent"
```

---

### Task 4: SwarmManager Core

The central swarm coordinator. Manages worker lifecycle, collects snapshots, ticks the orchestrator.

**Files:**
- Create: `swarm.py`
- Create: `tests/test_swarm.py`

**Step 1: Write the failing tests**

Create `tests/test_swarm.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_swarm.py -v`
Expected: FAIL — `swarm` module does not exist

**Step 3: Implement SwarmManager**

Create `swarm.py` with the full SwarmManager class including:
- `__init__` with max_workers, orchestrator creation, lock, worker dict
- `spawn_worker(goal, shell_cmd)` returning worker_id or None
- `kill_worker(worker_id)` removing and stopping worker
- `assign_goal(worker_id, goal)` updating goal and seeding history
- `get_all_snapshots()` collecting all agent snapshots
- `process_command(command)` dispatching assign/spawn/kill/wait
- `_start_worker_thread(worker_id)` starting worker loop in background thread
- `start()` and `stop()` for lifecycle
- `build_orchestrator_input()` formatting worker summaries for orchestrator
- `tick_orchestrator()` running one orchestrator think cycle

See the design doc for full implementation details. The class uses `threading.Lock` for the workers dict and creates `TerminalAgent` instances for each worker.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_swarm.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add swarm.py tests/test_swarm.py
git commit -m "feat: add SwarmManager with worker lifecycle and orchestrator commands"
```

---

### Task 5: Multiplexed WebSocket Server

Modify `web/server.py` to support multiplexed broadcasts tagged by agent_id, swarm events, and full swarm state snapshots. Add a `/swarm` endpoint for the new UI.

**Files:**
- Modify: `web/server.py`

**Step 1: Implement the new server**

Add to `web/server.py`:
- New module-level sets: `_swarm_clients`, `_latest_swarm_state`
- `GET /swarm` — serves `swarm.html`
- `GET /swarm/{filename}` — serves static JS/CSS files for swarm UI
- `WebSocket /swarm/ws` — swarm WebSocket endpoint with cached state on connect
- `async swarm_broadcast(message)` — send to all swarm clients
- `async broadcast_swarm_state(snapshots)` — broadcast full swarm state
- `async broadcast_swarm_event(event, agent_id, detail)` — broadcast lifecycle events

Keep all existing single-agent endpoints unchanged for backwards compatibility.

**Step 2: Verify existing tests still pass**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add web/server.py
git commit -m "feat: add multiplexed swarm WebSocket endpoints to server"
```

---

### Task 6: Swarm Entry Point

Add a `swarm_main()` function and CLI to `swarm.py` that starts the swarm manager, web server, and orchestrator loop.

**Files:**
- Modify: `swarm.py`

**Step 1: Add swarm_main**

Append to `swarm.py` a `swarm_main()` function that:
- Parses CLI args: `--orchestrator-model`, `--worker-model`, `--max-workers`, `--port`, `--goal`
- Creates SwarmManager
- Seeds orchestrator history with initial goal if provided
- Sets up SIGINT handler
- Starts uvicorn in background thread (same pattern as `agent.py:main()`)
- Runs main swarm loop: tick_orchestrator + broadcast_swarm_state + broadcast_swarm_event
- Sleeps `SWARM_BROADCAST_INTERVAL` between ticks
- Add `if __name__ == "__main__": swarm_main()`

**Step 2: Test it imports**

Run: `python -c "from swarm import SwarmManager; print('import OK')"`
Expected: `import OK`

**Step 3: Commit**

```bash
git add swarm.py
git commit -m "feat: add swarm_main() entry point with CLI and web broadcasting"
```

---

### Task 7: Cyberpunk Swarm HTML Shell

Create the base `swarm.html` with the cyberpunk layout: header, terminal grid, event log footer. No animations yet — just the structural HTML/CSS and xterm.js integration for multiple terminals.

**Files:**
- Create: `web/swarm.html`

**Step 1: Create swarm.html**

Create `web/swarm.html` with:
- CSS variables for neon color palette (cyan, green, yellow, red, magenta)
- Google Fonts: JetBrains Mono + Orbitron
- Header: "AGENT SWARM CONTROL" title (Orbitron font), status dot, worker count, tick counter
- Canvas elements for particle overlay and hex background (z-indexed behind content)
- CSS Grid container (3 columns x 3 rows) for terminal panels
- Orchestrator panel always in grid-column 1, grid-row 1/3 (double height)
- `.agent-panel` with state-based border colors via CSS classes (state-acting, state-thinking, etc.)
- borderPulse CSS animation for action events
- Thinking spinner CSS animation
- Matrix rain canvas per panel (opacity controlled by state classes)
- Footer event log div
- JavaScript: agents state object, terminal creation with xterm.js, dynamic worker panel creation/removal
- JavaScript: WebSocket connection to `/swarm/ws` with auto-reconnect
- JavaScript: message handler for `swarm_state` (update all agents) and `swarm_event` (add log entries)
- JavaScript: `updateAgentState()` function handling status classes, terminal content, pulse animation, spinner
- JavaScript: resize handler to refit all terminals
- Use `textContent` for all user-visible text updates (no innerHTML with untrusted data)
- Use DOM API (`createElement`, `appendChild`) for dynamic panel creation

**Step 2: Verify server serves the new page**

Run: `python -c "from web.server import app; print('server import OK')"`
Expected: `server import OK`

**Step 3: Commit**

```bash
git add web/swarm.html
git commit -m "feat: add cyberpunk swarm dashboard HTML with xterm.js grid"
```

---

### Task 8: Matrix Rain Animation

JavaScript module for matrix rain effect on idle terminal panels.

**Files:**
- Create: `web/matrix.js`
- Modify: `web/swarm.html` (add script tag)

**Step 1: Create matrix.js**

Create `web/matrix.js` with:
- `MatrixRain` class: takes a canvas element
  - `_resize()` — match canvas to parent bounds
  - `_draw()` — requestAnimationFrame loop: fade background, draw random katakana/hex chars in columns, green tint
  - `start()` / `stop()` — control animation
  - Character set: katakana + hex digits
  - Fading trail effect: fill with semi-transparent background each frame
  - Brighter "head" chars at 5% probability
  - Column reset when char reaches bottom with random probability
- `matrixInstances` object — cache of MatrixRain per agent_id
- `updateMatrixRain(agentId, status)` — start rain for idle/empty, stop for active states

**Step 2: Add script tag to swarm.html**

Add `<script src="/swarm/matrix.js"></script>` before the inline script.
Call `updateMatrixRain(agentId, agent.status)` in `updateAgentState()`.

**Step 3: Commit**

```bash
git add web/matrix.js web/swarm.html
git commit -m "feat: add matrix rain animation for idle terminal panels"
```

---

### Task 9: Particle System and Data Flow Lines

Canvas-based particle system showing data flowing from orchestrator to active workers. Includes hex grid background and action flash effects.

**Files:**
- Create: `web/particles.js`
- Modify: `web/swarm.html` (add script tag + init)

**Step 1: Create particles.js**

Create `web/particles.js` with:
- `ParticleSystem` class: takes the full-page particle canvas
  - `_resize()` — match canvas to window
  - `_getPanelCenter(panelId)` — get center coords of a panel element
  - `addFlowLine(sourceId, targetId, color)` — register animated data flow
  - `removeFlowLine(sourceId, targetId)` — remove flow line
  - `clearFlowLines()` — remove all
  - `flash(panelId, color)` — spawn 12 radial particles at panel center
  - `_spawnFlowParticle(flow)` — create particle at source, lerp toward target
  - `_update()` — move particles, remove expired ones
  - `_draw()` — render flow particles with glow, flash particles with decay
  - `start()` / `stop()` — control animation loop

- `HexBackground` class: takes the hex-bg canvas
  - `_resize()` — match canvas to window
  - `draw()` — draw hexagonal grid pattern in cyan, low opacity
  - `_drawHex(ctx, x, y, size)` — draw single hexagon

**Step 2: Add script tags and initialization to swarm.html**

Add `<script src="/swarm/particles.js"></script>` before inline script.
Initialize: `const particleSystem = new ParticleSystem(...)` and `const hexBg = new HexBackground(...)`.
In `updateAgentState()`:
- For active/thinking workers: `particleSystem.addFlowLine('panel-orchestrator', panelId, color)`
- For idle workers: `particleSystem.removeFlowLine(...)`
- On action change to acting: `particleSystem.flash(panelId)`

**Step 3: Commit**

```bash
git add web/particles.js web/swarm.html
git commit -m "feat: add particle data flow lines, hex background, action flash effects"
```

---

### Task 10: Integration Test and Polish

Wire everything together. Test the full swarm with a real orchestrator cycle. Fix any issues.

**Files:**
- Modify: any files needing fixes

**Step 1: Run all existing tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 2: Smoke test the swarm**

```bash
python -c "
from swarm import SwarmManager
import json

sm = SwarmManager(max_workers=4, web_enabled=False)
print('SwarmManager created')

wid = sm.spawn_worker(goal='test goal', shell_cmd='echo hello')
print(f'Spawned: {wid}')

snaps = sm.get_all_snapshots()
print(f'Snapshots: {list(snaps.keys())}')

inp = sm.build_orchestrator_input()
print(f'Orchestrator input ({len(inp)} chars)')

sm.kill_worker(wid)
print(f'Killed {wid}, workers: {len(sm.workers)}')

print('All smoke tests passed')
"
```

**Step 3: Run full swarm**

```bash
python swarm.py --goal "Use different AI models to explore the system. Spawn workers that run ollama run llama3.2 and other tools." --port 8765
```

Open: `http://localhost:8765/swarm`

**Step 4: Fix any issues found and commit**

```bash
git add -A
git commit -m "feat: complete agent swarm with cyberpunk UI, matrix rain, particle effects"
```

---

## Task Summary

| Task | Component | Files | Dependencies |
|------|-----------|-------|-------------|
| 1 | get_snapshot() for TerminalAgent | agent.py, tests/test_agent.py | None |
| 2 | Swarm config defaults | config.py | None |
| 3 | Orchestrator system prompt | ollama_client.py, tests/test_ollama_client.py | None |
| 4 | SwarmManager core | swarm.py, tests/test_swarm.py | Tasks 1, 2, 3 |
| 5 | Multiplexed WebSocket server | web/server.py | None |
| 6 | Swarm entry point (swarm_main) | swarm.py | Tasks 4, 5 |
| 7 | Cyberpunk HTML shell | web/swarm.html | Task 5 |
| 8 | Matrix rain animation | web/matrix.js, web/swarm.html | Task 7 |
| 9 | Particle system and data lines | web/particles.js, web/swarm.html | Task 7 |
| 10 | Integration test and polish | all | Tasks 1-9 |

**Parallel-safe tasks**: Tasks 1, 2, 3, 5 can all run in parallel. Tasks 7, 8, 9 can run in parallel after Task 5.
