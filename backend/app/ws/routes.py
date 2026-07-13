from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.security import decode_access_token
from app.ws.manager import manager

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    token = websocket.cookies.get("access_token")
    if token is None:
        await websocket.close(code=4401)
        return
    try:
        decode_access_token(token)
    except Exception:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # client doesn't send anything meaningful; keeps connection open
    except WebSocketDisconnect:
        manager.disconnect(websocket)
