import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def send_json(self, data: dict) -> None: ...
    async def close(self) -> None: ...


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocketLike] = []

    async def connect(self, websocket: WebSocketLike) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocketLike) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, data: dict[str, Any]) -> None:
        for connection in list(self._connections):
            try:
                await connection.send_json(data)
            except Exception as exc:  # noqa: BLE001 - drop dead connections
                logger.debug("Dropping WebSocket connection after send failure: %s", exc)
                self.disconnect(connection)


manager = ConnectionManager()
