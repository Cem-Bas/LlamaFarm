from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

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
