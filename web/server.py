from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

app = FastAPI()
_clients: set[WebSocket] = set()
_latest_state: dict = {}

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
    _clients -= dead


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
    content_type = "application/javascript" if filename.endswith(".js") else "text/css"
    return Response(content=file_path.read_text(), media_type=content_type)


@app.websocket("/swarm/ws")
async def swarm_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _swarm_clients.add(websocket)
    try:
        if _latest_swarm_state:
            await websocket.send_json(_latest_swarm_state)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _swarm_clients.discard(websocket)


async def swarm_broadcast(message: dict) -> None:
    dead = set()
    for client in _swarm_clients:
        try:
            await client.send_json(message)
        except Exception:
            dead.add(client)
    _swarm_clients -= dead


async def broadcast_swarm_state(snapshots: dict) -> None:
    message = {"type": "swarm_state", "agents": snapshots}
    _latest_swarm_state.update(message)
    await swarm_broadcast(message)


async def broadcast_swarm_event(event: str, agent_id: str, detail: str = "") -> None:
    message = {"type": "swarm_event", "event": event, "agent_id": agent_id, "detail": detail}
    await swarm_broadcast(message)
