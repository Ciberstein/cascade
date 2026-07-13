import asyncio

from aiohttp import web


class FlakyTestServer:
    def __init__(self, payload: bytes, support_range: bool = True, fail_first_n: int = 0):
        self.payload = payload
        self.support_range = support_range
        self.fail_first_n = fail_first_n
        self._attempts = 0
        self.app = web.Application()
        # allow_head=False: aiohttp's add_get auto-registers a HEAD route by
        # default, which would collide with the explicit add_head below.
        self.app.router.add_get("/file", self._handle, allow_head=False)
        self.app.router.add_head("/file", self._handle_head)
        self.runner: web.AppRunner | None = None
        self.port: int | None = None

    async def start(self) -> str:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{self.port}/file"

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()

    async def _handle_head(self, request: web.Request) -> web.Response:
        headers = {"Content-Length": str(len(self.payload))}
        if self.support_range:
            headers["Accept-Ranges"] = "bytes"
        return web.Response(status=200, headers=headers)

    async def _handle(self, request: web.Request) -> web.Response:
        self._attempts += 1
        if self._attempts <= self.fail_first_n:
            return web.Response(status=503)

        range_header = request.headers.get("Range")
        if range_header and self.support_range:
            start, end = range_header.replace("bytes=", "").split("-")
            start, end = int(start), int(end)
            body = self.payload[start : end + 1]
            return web.Response(
                status=206,
                body=body,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{len(self.payload)}",
                    "Content-Length": str(len(body)),
                },
            )

        return web.Response(status=200, body=self.payload)
