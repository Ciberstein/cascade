from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.owner import owner_from_query
from app.ws.manager import manager

router = APIRouter()

#: Closed with this code when the owner token is missing or invalid. The
#: client tells it apart from a network drop and does not retry in a loop.
INVALID_OWNER = 4401


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, owner: str | None = None):
    # Query string rather than header: the browser's WebSocket API does not
    # allow sending headers of its own during the handshake.
    owner_id = owner_from_query(owner)
    if owner_id is None:
        await websocket.close(code=INVALID_OWNER)
        return

    await manager.connect(websocket, owner_id)
    try:
        while True:
            await websocket.receive_text()  # client doesn't send anything meaningful; keeps connection open
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
