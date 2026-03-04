import asyncio
import json
from pathlib import Path

import ollama as ollama_pkg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

app = FastAPI()
_clients: set[WebSocket] = set()
_latest_state: dict = {}

# --- Capture the REAL event loop uvicorn is running on ---
_uvicorn_loop = None


@app.on_event("startup")
async def _capture_loop():
    global _uvicorn_loop
    _uvicorn_loop = asyncio.get_running_loop()
    print(f"[WS] Captured uvicorn event loop: {id(_uvicorn_loop)}")


def get_uvicorn_loop():
    """Return the actual event loop uvicorn is running on."""
    return _uvicorn_loop

# --- Swarm manager reference (set by swarm_main) ---
_swarm_manager = None


def set_swarm_manager(manager) -> None:
    """Register the SwarmManager instance so the web layer can send commands."""
    global _swarm_manager
    _swarm_manager = manager

@app.get("/")
async def index():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(html_path.read_text())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    try:
        if _latest_state:
            await websocket.send_json(_latest_state)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)

async def broadcast(screen_text: str, action: dict, iteration: int) -> None:
    message = {
        "type": "screen",
        "content": screen_text,
        "action": action,
        "iteration": iteration,
    }
    _latest_state.update(message)
    dead = set()
    for client in _clients:
        try:
            await client.send_json(message)
        except Exception:
            dead.add(client)
    _clients.difference_update(dead)


# --- Swarm endpoints ---

_swarm_clients: set[WebSocket] = set()
_latest_swarm_state: dict = {}


@app.get("/swarm")
async def swarm_index():
    html_path = Path(__file__).parent / "swarm.html"
    return HTMLResponse(html_path.read_text())


@app.get("/swarm/{filename}")
async def swarm_static(filename: str):
    file_path = Path(__file__).parent / filename
    if not file_path.exists() or not file_path.is_file():
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(file_path)


@app.get("/api/swarm/models")
async def swarm_models():
    """Return available Ollama models plus CLI agents."""
    models = []

    # Add CLI agents first
    cli_agents = [
        {"name": "claude-cli", "size": 0, "family": "cli", "parameter_size": "cloud", "quantization": ""},
        {"name": "codex-cli", "size": 0, "family": "cli", "parameter_size": "cloud", "quantization": ""},
        {"name": "gemini-cli", "size": 0, "family": "cli", "parameter_size": "cloud", "quantization": ""},
    ]
    models.extend(cli_agents)

    # Add Ollama models
    try:
        resp = ollama_pkg.list()
        for m in resp.models:
            details = m.details
            models.append({
                "name": m.model,
                "size": m.size,
                "family": details.family if details else "",
                "parameter_size": details.parameter_size if details else "",
                "quantization": details.quantization_level if details else "",
            })
    except Exception as e:
        pass  # Ollama may not be running; CLI agents still available

    return JSONResponse({"models": models})


@app.websocket("/swarm/ws")
async def swarm_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _swarm_clients.add(websocket)
    try:
        if _latest_swarm_state:
            await websocket.send_json(_latest_swarm_state)
        while True:
            raw = await websocket.receive_text()
            # Try to parse as a command
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            command = msg.get("command", "")
            if not command or _swarm_manager is None:
                await websocket.send_json({
                    "type": "error",
                    "command": command,
                    "message": "No swarm manager" if not _swarm_manager else "Missing command",
                })
                continue

            try:
                if command == "spawn":
                    goal = msg.get("goal", "")
                    model = msg.get("model", "")
                    shell_cmd = msg.get("shell_cmd", "")
                    worker_id = _swarm_manager.spawn_worker(
                        goal=goal, model=model, shell_cmd=shell_cmd,
                    )
                    if worker_id is None:
                        await websocket.send_json({
                            "type": "error", "command": "spawn",
                            "message": "Max workers reached",
                        })
                    else:
                        _swarm_manager._start_worker_thread(worker_id)
                        await websocket.send_json({
                            "type": "ack", "command": "spawn",
                            "worker_id": worker_id,
                        })
                        await broadcast_swarm_event("worker_spawned", worker_id, goal)
                        # Immediately broadcast updated state so the UI doesn't
                        # have to wait for the next orchestrator tick (which can
                        # block on a slow Ollama call for many seconds).
                        snapshots = _swarm_manager.get_all_snapshots()
                        await broadcast_swarm_state(snapshots)

                elif command == "kill":
                    worker_id = msg.get("worker_id", "")
                    _swarm_manager.kill_worker(worker_id)
                    await websocket.send_json({
                        "type": "ack", "command": "kill",
                        "worker_id": worker_id,
                    })
                    await broadcast_swarm_event("worker_killed", worker_id)
                    # Immediately broadcast so removed worker disappears
                    snapshots = _swarm_manager.get_all_snapshots()
                    await broadcast_swarm_state(snapshots)

                elif command == "assign_goal":
                    worker_id = msg.get("worker_id", "")
                    goal = msg.get("goal", "")
                    _swarm_manager.assign_goal(worker_id, goal)
                    await websocket.send_json({
                        "type": "ack", "command": "assign_goal",
                        "worker_id": worker_id, "goal": goal,
                    })
                    await broadcast_swarm_event("goal_assigned", worker_id, goal)

                elif command == "set_worker_model":
                    model = msg.get("model", "")
                    _swarm_manager.worker_model = model
                    await websocket.send_json({
                        "type": "ack", "command": "set_worker_model",
                        "model": model,
                    })
                    await broadcast_swarm_event("worker_model_changed", "swarm", model)

                elif command == "get_config":
                    await websocket.send_json({
                        "type": "config",
                        "worker_model": _swarm_manager.worker_model,
                        "orchestrator_model": _swarm_manager.orchestrator_model,
                        "max_workers": _swarm_manager.max_workers,
                    })

                elif command == "kill_all":
                    result = _swarm_manager.kill_all()
                    await websocket.send_json({
                        "type": "ack", "command": "kill_all",
                        "killed": result["killed_workers"],
                        "count": result["count"],
                    })
                    await broadcast_swarm_event(
                        "kill_all", "swarm",
                        f"Killed {result['count']} workers: {', '.join(result['killed_workers']) if result['killed_workers'] else 'none active'}",
                    )
                    # Broadcast clean state immediately
                    snapshots = _swarm_manager.get_all_snapshots()
                    await broadcast_swarm_state(snapshots)

                elif command == "set_orchestrator_goal":
                    goal = msg.get("goal", "")
                    _swarm_manager.orchestrator.goal = goal
                    _swarm_manager._orch_agent.goal = goal
                    await websocket.send_json({
                        "type": "ack", "command": "set_orchestrator_goal",
                        "goal": goal,
                    })
                    await broadcast_swarm_event("mission_set", "orchestrator", goal)

                elif command == "send_message":
                    agent_id = msg.get("agent_id", "")
                    message_text = msg.get("message", "")
                    if not message_text:
                        await websocket.send_json({
                            "type": "error", "command": "send_message",
                            "message": "Empty message",
                        })
                    elif agent_id == "orchestrator":
                        _swarm_manager.queue_message(message_text)
                        await websocket.send_json({
                            "type": "ack", "command": "send_message",
                            "agent_id": agent_id, "message": message_text,
                        })
                        await broadcast_swarm_event("user_message", agent_id, message_text)
                    else:
                        # Send to a specific worker
                        with _swarm_manager._lock:
                            worker = _swarm_manager.workers.get(agent_id)
                        if worker is None:
                            await websocket.send_json({
                                "type": "error", "command": "send_message",
                                "message": f"Agent {agent_id} not found",
                            })
                        else:
                            worker["agent"].ollama._history.append({
                                "role": "user",
                                "content": f"[USER MESSAGE] {message_text}",
                            })
                            await websocket.send_json({
                                "type": "ack", "command": "send_message",
                                "agent_id": agent_id, "message": message_text,
                            })
                            await broadcast_swarm_event("user_message", agent_id, message_text)

                else:
                    await websocket.send_json({
                        "type": "error", "command": command,
                        "message": f"Unknown command: {command}",
                    })

            except Exception as e:
                await websocket.send_json({
                    "type": "error", "command": command,
                    "message": str(e),
                })

    except WebSocketDisconnect:
        pass
    finally:
        _swarm_clients.discard(websocket)


async def swarm_broadcast(message: dict) -> None:
    if not _swarm_clients:
        return
    dead = set()
    for client in _swarm_clients:
        try:
            await client.send_json(message)
        except Exception as e:
            print(f"[WS] broadcast error: {e}")
            dead.add(client)
    if dead:
        print(f"[WS] removing {len(dead)} dead client(s)")
        _swarm_clients.difference_update(dead)


async def broadcast_swarm_state(snapshots: dict, tick: int = 0) -> None:
    # Pre-validate JSON serialisation to catch issues early
    try:
        json.dumps(snapshots)
    except (TypeError, ValueError) as e:
        print(f"[WS] snapshot not serialisable: {e}")
        # Sanitise: convert everything to strings as a fallback
        safe = {}
        for k, v in snapshots.items():
            try:
                json.dumps(v)
                safe[k] = v
            except (TypeError, ValueError):
                safe[k] = {"agent_id": k, "status": "unknown", "iteration": 0,
                           "last_action": None, "screen_text": "", "goal": ""}
        snapshots = safe

    message = {"type": "swarm_state", "agents": snapshots, "tick": tick}
    _latest_swarm_state.update(message)
    try:
        await swarm_broadcast(message)
    except Exception as e:
        print(f"[WS] broadcast_swarm_state error: {e}")


async def broadcast_swarm_event(event: str, agent_id: str, detail: str = "") -> None:
    message = {"type": "swarm_event", "event": event, "agent_id": agent_id, "detail": detail}
    await swarm_broadcast(message)
