from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.owner import owner_from_query
from app.ws.manager import manager

router = APIRouter()

#: Se cierra con este código cuando falta el token de dueño o es inválido. El
#: cliente lo distingue de una caída de red y no reintenta en bucle.
INVALID_OWNER = 4401


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, owner: str | None = None):
    # Por query string y no por cabecera: la API de WebSocket del navegador no
    # deja mandar cabeceras propias en el handshake.
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
