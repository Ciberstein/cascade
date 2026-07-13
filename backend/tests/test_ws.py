import pytest

from app.ws.manager import ConnectionManager


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


@pytest.mark.asyncio
async def test_connection_manager_broadcasts_to_all_connected():
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect(ws1)
    await manager.connect(ws2)

    await manager.broadcast({"type": "progress", "item_id": "abc", "downloaded_bytes": 100})

    assert ws1.sent == [{"type": "progress", "item_id": "abc", "downloaded_bytes": 100}]
    assert ws2.sent == ws1.sent


@pytest.mark.asyncio
async def test_connection_manager_stops_sending_to_disconnected():
    manager = ConnectionManager()
    ws1 = FakeWebSocket()
    await manager.connect(ws1)
    manager.disconnect(ws1)

    await manager.broadcast({"type": "progress"})

    assert ws1.sent == []


@pytest.mark.asyncio
async def test_connection_manager_drops_dead_connection_without_breaking_broadcast():
    manager = ConnectionManager()

    class DeadWebSocket(FakeWebSocket):
        async def send_json(self, data: dict):
            raise RuntimeError("connection is dead")

    dead = DeadWebSocket()
    alive = FakeWebSocket()
    await manager.connect(dead)
    await manager.connect(alive)

    await manager.broadcast({"type": "progress"})

    assert alive.sent == [{"type": "progress"}]
    assert dead not in manager._connections


def test_ws_route_rejects_connection_without_cookie(client):
    from fastapi import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws"):
            pass
    assert exc_info.value.code == 4401


def test_ws_route_rejects_connection_with_invalid_cookie(client):
    from fastapi import WebSocketDisconnect

    client.cookies.set("access_token", "not-a-valid-jwt")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws"):
            pass
    assert exc_info.value.code == 4401


def test_ws_route_accepts_connection_with_valid_cookie(auth_client):
    with auth_client.websocket_connect("/ws") as websocket:
        # connection accepted; no exception raised on entry
        assert websocket is not None
