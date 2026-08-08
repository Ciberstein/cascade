import asyncio

from aiohttp import web


class FlakyTestServer:
    def __init__(
        self,
        payload: bytes,
        support_range: bool = True,
        fail_first_n: int = 0,
        ignore_range: bool = False,
        head_status: int = 200,
        omit_content_length: bool = False,
        stream_delay_seconds: float = 0.0,
        stream_parts: int = 8,
    ):
        self.payload = payload
        self.support_range = support_range
        self.fail_first_n = fail_first_n
        # When True, always returns the full payload with status 200 even if
        # a Range header was sent - simulates a server that advertises range
        # support (e.g. via Accept-Ranges on HEAD) but doesn't honor it on GET.
        self.ignore_range = ignore_range
        # Lets tests simulate a HEAD probe failure (404/403/405 etc).
        self.head_status = head_status
        # Lets tests simulate a server that omits Content-Length on HEAD
        # (e.g. chunked transfer encoding) instead of returning a real size.
        self.omit_content_length = omit_content_length
        # When > 0, the body is sent in `stream_parts` pieces with this delay
        # between them. Lets a test observe a download *while it is running*
        # without racing loopback throughput, which otherwise delivers the
        # whole payload before any periodic work gets a chance to tick.
        self.stream_delay_seconds = stream_delay_seconds
        self.stream_parts = stream_parts
        self._attempts = 0
        # Every Range header served, in order, as (start, end). Lets a test
        # assert where a download actually started reading from - the only way
        # to tell a real resume from a re-download that happens to produce the
        # same file.
        self.requested_ranges: list[tuple[int, int]] = []
        #: Headers de cada request servida, para poder afirmar qué mandó el motor.
        self.seen_headers: list[dict[str, str]] = []
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

    async def _handle_head(self, request: web.Request) -> web.StreamResponse:
        self.seen_headers.append(dict(request.headers))
        if self.head_status != 200:
            return web.Response(status=self.head_status)

        if self.omit_content_length:
            # Use a chunked StreamResponse so aiohttp doesn't auto-populate
            # Content-Length - simulates servers using chunked transfer
            # encoding on HEAD instead of advertising a real size.
            response = web.StreamResponse(status=200)
            response.enable_chunked_encoding()
            if self.support_range:
                response.headers["Accept-Ranges"] = "bytes"
            await response.prepare(request)
            return response

        headers = {"Content-Length": str(len(self.payload))}
        if self.support_range:
            headers["Accept-Ranges"] = "bytes"
        return web.Response(status=200, headers=headers)

    async def _handle(self, request: web.Request) -> web.Response:
        self.seen_headers.append(dict(request.headers))
        self._attempts += 1
        if self._attempts <= self.fail_first_n:
            return web.Response(status=503)

        range_header = request.headers.get("Range")
        if range_header and self.support_range and not self.ignore_range:
            start, end = range_header.replace("bytes=", "").split("-")
            start, end = int(start), int(end)
            self.requested_ranges.append((start, end))
            body = self.payload[start : end + 1]
            headers = {
                "Content-Range": f"bytes {start}-{end}/{len(self.payload)}",
                "Content-Length": str(len(body)),
            }
            if self.stream_delay_seconds > 0:
                return await self._stream(request, body, status=206, headers=headers)
            return web.Response(status=206, body=body, headers=headers)

        if self.stream_delay_seconds > 0:
            return await self._stream(
                request, self.payload, status=200, headers={"Content-Length": str(len(self.payload))}
            )
        return web.Response(status=200, body=self.payload)

    async def _stream(
        self, request: web.Request, body: bytes, status: int, headers: dict
    ) -> web.StreamResponse:
        response = web.StreamResponse(status=status, headers=headers)
        await response.prepare(request)

        size = max(1, -(-len(body) // self.stream_parts))  # ceil division
        for offset in range(0, len(body), size):
            await response.write(body[offset : offset + size])
            await asyncio.sleep(self.stream_delay_seconds)
        await response.write_eof()
        return response
