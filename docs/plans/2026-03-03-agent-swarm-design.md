# Agent Swarm with Cyberpunk UI — Design Document

## Goal

Extend the single-agent terminal controller into a multi-agent swarm where a local Ollama orchestrator manages up to 8 worker agents, each controlling a PTY that can run any CLI tool (ollama run, gemini, codex, claude, etc.). Monitored via a cyberpunk-themed web dashboard.

## Architecture

### Pattern: Multi-Process Orchestrator

```
Orchestrator (devstral-small-2)
    ↓ assigns goals / spawns / kills
SwarmManager
    ↓ manages threads
Worker 0 (PTY → bash → "ollama run llama3.2")
Worker 1 (PTY → bash → "gemini")
Worker 2 (PTY → bash → "codex")
...up to 8
    ↓ all broadcast via WebSocket
Cyberpunk Web UI (grid of xterm.js terminals)
```

### Core Components

**SwarmManager** — top-level coordinator:
- Manages a dict of WorkerAgent instances (up to 8) + 1 OrchestratorAgent
- Each worker has: agent_id, TerminalAgent instance, goal, status, thread
- Owns the web broadcast — sends all agent states to the UI every 500ms
- Thread-safe snapshot collection via threading.Lock

**OrchestratorAgent** — the boss:
- Runs devstral-small-2 with a special system prompt
- Every tick receives JSON summary of all workers: {worker_id, goal, status, last_action, screen_snippet}
- Returns commands: assign, spawn, kill, wait
- Has its own PTY for direct terminal work if needed

**WorkerAgent** — each worker:
- Extends existing TerminalAgent — same Observe-Think-Act loop
- Gets a goal assigned by the orchestrator
- Runs in its own thread with its own PTY (bash shell)
- Can launch ollama run, gemini, codex, claude — any CLI tool
- Reports status back to SwarmManager via shared state snapshots

### Agent Lifecycle States

```
spawning → idle → assigned → thinking → acting → idle (loop)
                                              ↘ error → idle
                              killed ←─────────────────┘
```

## Threading Model

```
Main Thread:     SwarmManager.run() — ticks orchestrator, collects state, broadcasts
Thread 1:        Orchestrator TerminalAgent.run_loop()
Thread 2-9:      Worker TerminalAgent.run_loop() (up to 8)
Uvicorn Thread:  FastAPI + WebSocket server
```

### Thread Safety

- SwarmManager._agents: dict protected by threading.Lock
- Each agent exposes read-only snapshots via agent.get_snapshot() -> dict
- Orchestrator reads snapshots, never touches worker internals
- SwarmManager collects snapshots and broadcasts — no lock contention on hot path

## WebSocket Protocol

Single multiplexed WebSocket connection tagged by agent_id:

```json
// Screen update (per agent)
{
  "type": "screen",
  "agent_id": "orchestrator",
  "screen_text": "...",
  "action": {"action": "type", "value": "ls"},
  "iteration": 5,
  "status": "acting",
  "goal": "Coordinate workers"
}

// Swarm events
{
  "type": "swarm_event",
  "event": "worker_spawned",
  "agent_id": "worker-03",
  "detail": "gemini"
}

// Full swarm state (on connect + periodically)
{
  "type": "swarm_state",
  "agents": {
    "orchestrator": {"status": "thinking", "goal": "...", "iteration": 12},
    "worker-01": {"status": "acting", "goal": "...", "iteration": 8}
  }
}
```

## Cyberpunk Web UI

### Layout

Tiled grid of xterm.js terminals. Orchestrator panel is larger/prominent (top-left, double-width). Workers fill remaining grid cells. Event log ticker at bottom.

### Animations

- **Matrix rain**: Green cascading characters on idle/disconnected terminals (Canvas)
- **Neon glow borders**: Color per state — cyan (orchestrator), green (acting), yellow (thinking), red (error), dim gray (idle)
- **Pulse effect**: Border glows brighter on new action, fades over 1s (CSS animation)
- **Particle data lines**: Animated dots flow from orchestrator to active workers (Canvas overlay)
- **Hexagonal grid background**: Subtle animated hex pattern, low opacity
- **Action flash**: Brief particle burst when agent executes a command
- **Status spinners**: Animated ring spinner on "thinking" state
- **Event log ticker**: Auto-scrolling neon-green monospace log at bottom

### Tech Stack

- xterm.js per terminal panel (one instance per agent)
- Canvas overlay for particle effects and data flow lines
- CSS animations for glow/pulse (GPU-accelerated)
- Single WebSocket, multiplexed by agent_id
- requestAnimationFrame loop for particles + matrix rain

## Resource Budget (36GB M4 Max)

| Component | Memory | Notes |
|-----------|--------|-------|
| devstral-small-2 (shared) | ~17GB | 100% GPU, 8K ctx |
| Worker PTYs (8x) | ~50MB total | Lightweight bash processes |
| pyte screens (9x) | ~20MB total | 120x40 char buffers |
| Ollama history (9x) | ~100MB total | 20 message pairs each |
| Web UI + xterm.js | Browser-side | No server cost |

Workers that spawn `ollama run llama3.2` inside their PTY run a separate Ollama chat session — the worker agent observes and types into it.

## Error Handling

- **Worker crash**: SwarmManager catches it, sets status to error, notifies orchestrator. Can respawn.
- **Ollama timeout**: Returns fallback wait action. Worker retries next tick.
- **Orchestrator crash**: SwarmManager restarts orchestrator thread. Workers continue independently.
- **WebSocket disconnect**: Client auto-reconnects, receives full swarm_state snapshot.
- **All workers busy**: Orchestrator told "all workers assigned", can kill/reassign or wait.

## File Structure

```
ollama-terminal-agent/
├── swarm.py              # NEW — SwarmManager, WorkerAgent, OrchestratorAgent
├── agent.py              # MODIFY — add get_snapshot(), extract reusable parts
├── config.py             # MODIFY — add swarm defaults
├── ollama_client.py      # MODIFY — add orchestrator system prompt
├── web/
│   ├── server.py         # MODIFY — multiplexed broadcast, swarm endpoints
│   ├── swarm.html        # NEW — cyberpunk swarm dashboard
│   ├── particles.js      # NEW — Canvas particle system + data flow lines
│   └── matrix.js         # NEW — Matrix rain effect
├── tests/
│   ├── test_swarm.py     # NEW — swarm lifecycle tests
│   └── test_agent.py     # MODIFY — add snapshot tests
```

## Orchestrator System Prompt (Summary)

Describes role as swarm coordinator. Lists available workers and their states. Defines command JSON format (assign/spawn/kill/wait). Lists available CLI tools. Updated every tick with fresh worker summaries.
