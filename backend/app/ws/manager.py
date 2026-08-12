import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def send_json(self, data: dict) -> None: ...
    async def close(self) -> None: ...


class ConnectionManager:
    """Open connections, each tied to its owner.

    Progress is delivered only to whoever owns that download. Without that
    separation, a single broadcast to everyone would leak every visitor the ids
    and the progress of other people's downloads.
    """

    def __init__(self) -> None:
        self._connections: list[tuple[str, WebSocketLike]] = []

    async def connect(self, websocket: WebSocketLike, owner_id: str) -> None:
        await websocket.accept()
        self._connections.append((owner_id, websocket))

    def disconnect(self, websocket: WebSocketLike) -> None:
        self._connections = [(o, w) for o, w in self._connections if w is not websocket]

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Sends `data` to its owner's connections.

        The owner travels inside the payload and is stripped before sending: it
        tells the manager who to deliver to, and adds nothing for the client.
        """
        owner_id = data.get("owner_id")
        payload = {k: v for k, v in data.items() if k != "owner_id"}

        for connection_owner, connection in list(self._connections):
            if owner_id is not None and connection_owner != owner_id:
                continue
            try:
                await connection.send_json(payload)
            except Exception as exc:  # noqa: BLE001 - drop dead connections
                logger.debug("Dropping WebSocket connection after send failure: %s", exc)
                self.disconnect(connection)


manager = ConnectionManager()
