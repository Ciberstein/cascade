import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def send_json(self, data: dict) -> None: ...
    async def close(self) -> None: ...


class ConnectionManager:
    """Conexiones abiertas, cada una atada a su dueño.

    El progreso se entrega solo a quien es dueño de esa descarga. Sin esa
    separación, una única emisión a todos filtraría a cada visitante los ids y
    el avance de las descargas ajenas.
    """

    def __init__(self) -> None:
        self._connections: list[tuple[str, WebSocketLike]] = []

    async def connect(self, websocket: WebSocketLike, owner_id: str) -> None:
        await websocket.accept()
        self._connections.append((owner_id, websocket))

    def disconnect(self, websocket: WebSocketLike) -> None:
        self._connections = [(o, w) for o, w in self._connections if w is not websocket]

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Envía `data` a las conexiones de su dueño.

        El dueño viaja dentro del payload y se quita antes de enviarlo: le dice
        al manager a quién entregar, y al cliente no le aporta nada.
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
