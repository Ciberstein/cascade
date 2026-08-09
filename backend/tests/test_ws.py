import pytest

from app.ws.manager import ConnectionManager
from tests.conftest import TEST_OWNER

OTHER_OWNER = "otroowner0000000000000000000000b"


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data: dict):
        self.sent.append(data)

    async def close(self):
        self.closed = True


def progress(owner: str | None = TEST_OWNER) -> dict:
    return {"type": "progress", "item_id": "abc", "downloaded_bytes": 100, "owner_id": owner}


@pytest.mark.asyncio
async def test_progress_reaches_every_connection_of_its_owner():
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect(ws1, TEST_OWNER)
    await manager.connect(ws2, TEST_OWNER)

    await manager.broadcast(progress())

    # El dueño se quita antes de enviar: le dice al manager a quién entregar y
    # al cliente no le aporta nada.
    assert ws1.sent == [{"type": "progress", "item_id": "abc", "downloaded_bytes": 100}]
    assert ws2.sent == ws1.sent


@pytest.mark.asyncio
async def test_progress_never_reaches_another_owner():
    manager = ConnectionManager()
    mine, theirs = FakeWebSocket(), FakeWebSocket()
    await manager.connect(mine, TEST_OWNER)
    await manager.connect(theirs, OTHER_OWNER)

    await manager.broadcast(progress())

    # Sin este filtro, una única emisión a todos le filtraría a cada visitante
    # los ids y el avance de las descargas ajenas.
    assert len(mine.sent) == 1
    assert theirs.sent == []


@pytest.mark.asyncio
async def test_a_disconnected_socket_stops_receiving():
    manager = ConnectionManager()
    ws1 = FakeWebSocket()
    await manager.connect(ws1, TEST_OWNER)
    manager.disconnect(ws1)

    await manager.broadcast(progress())

    assert ws1.sent == []


@pytest.mark.asyncio
async def test_a_dead_connection_is_dropped_without_breaking_the_broadcast():
    manager = ConnectionManager()

    class DeadWebSocket(FakeWebSocket):
        async def send_json(self, data: dict):
            raise RuntimeError("connection is dead")

    dead, alive = DeadWebSocket(), FakeWebSocket()
    await manager.connect(dead, TEST_OWNER)
    await manager.connect(alive, TEST_OWNER)

    await manager.broadcast(progress())

    assert len(alive.sent) == 1
    assert all(ws is not dead for _, ws in manager._connections)


def test_ws_route_rejects_a_connection_without_an_owner(client):
    from fastapi import WebSocketDisconnect

    # Sin login, pero el socket igual necesita saber a quién le habla.
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws"):
            pass
    assert exc_info.value.code == 4401


def test_ws_route_rejects_a_guessable_owner(client):
    from fastapi import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws?owner=abc"):
            pass
    assert exc_info.value.code == 4401


def test_ws_route_accepts_a_valid_owner(client):
    # Por query string: la API de WebSocket del navegador no deja mandar
    # cabeceras propias en el handshake.
    with client.websocket_connect(f"/ws?owner={TEST_OWNER}") as websocket:
        assert websocket is not None
