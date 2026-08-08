# Cascade Fase 2 — Sistema de plugins para hosters — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir un enlace de hoster en algo descargable — descubrir qué archivos hay detrás de un link, dejar que el usuario elija cuáles, y resolver la URL directa recién en el momento de bajar.

**Architecture:** Un plugin expone dos operaciones distintas: `crawl` (al agregar: qué archivos hay detrás) y `resolve` (al descargar: dame la URL directa, que caduca). El LinkGrabber es un subsistema propio con sus tablas y su loop, y promueve resultados a `packages`/`download_items`; el scheduler de Fase 1 no cambia su contrato, solo gana un filtro por `retry_after` y llama a `resolve` donde antes llamaba a `identity`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, httpx (con `MockTransport` para tests), selectolax (parser HTML), pytest/pytest-asyncio. Frontend React 19 + Vite + Vitest.

**Spec:** `docs/superpowers/specs/2026-08-08-cascade-phase2-design.md`

---

## File Structure

**Backend — nuevo**

| Archivo | Responsabilidad |
|---|---|
| `backend/app/plugins/base.py` | Contrato `Hoster`, dataclasses de retorno, excepciones tipadas. Sin I/O. |
| `backend/app/plugins/registry.py` | Descubrimiento de módulos, matching por URL, timeout y normalización de errores. |
| `backend/app/plugins/direct.py` | Fallback: devuelve la URL tal cual. Preserva el comportamiento de Fase 1. |
| `backend/app/plugins/open_directory.py` | Expande un índice de directorio (nginx/Apache autoindex) en N archivos. |
| `backend/app/plugins/pixeldrain.py` | Hoster real vía API JSON. Cubre archivo suelto y álbum. |
| `backend/app/crawler/core.py` | Recorre un link con recursión acotada y devuelve archivos descubiertos. Sin DB. |
| `backend/app/crawler/runner.py` | Toma `crawl_jobs` pendientes y escribe `crawl_results`. Con DB. |
| `backend/app/api/crawl_jobs.py` | Endpoints del grabber, incluido el de promoción a paquete. |
| `backend/alembic/versions/0002_plugins.py` | Migración de las dos tablas y las tres columnas nuevas. |

**Backend — modificado**

| Archivo | Cambio |
|---|---|
| `app/models.py` | `CrawlJob`, `CrawlResult`; `DownloadItem.hoster`/`.retry_after`; `GlobalSettings.max_concurrent_crawls`. |
| `app/schemas.py` | Schemas del grabber; `hoster`/`retry_after` en la respuesta de item; `max_concurrent_crawls` en settings. |
| `app/engine/downloader.py` | `download_chunk` acepta headers extra. |
| `app/engine/item_runner.py` | Propaga headers al probe y a cada chunk. |
| `app/engine/scheduler.py` | `identity` → `resolver`; filtro `retry_after`; `RateLimited` reagenda en vez de fallar. |
| `app/main.py` | Loop de crawl; resolver real; `max_concurrent_crawls`. |
| `app/api/packages.py` | `hoster='direct'` al crear items desde el endpoint clásico. |

**Frontend**

| Archivo | Cambio |
|---|---|
| `src/api/crawl.ts` | Nuevo. Cliente de los endpoints del grabber. |
| `src/pages/LinkGrabber.tsx` + `.css` | Nuevo. Bandeja de resultados. |
| `src/types.ts` | `CrawlJob`, `CrawlResult`; `hoster`/`retry_after` en `DownloadItem`. |
| `src/components/AddLinksModal.tsx` | Su submit pasa a crear un crawl job. |
| `src/pages/Dashboard.tsx` | Vista `grabber`; navegación. |
| `src/components/PackageRow.tsx` | Muestra "esperando hasta HH:MM". |
| `src/pages/Settings.tsx` | Control de `max_concurrent_crawls`. |

---

## Task 1: Contrato del plugin y excepciones

**Files:**
- Create: `backend/app/plugins/__init__.py`
- Create: `backend/app/plugins/base.py`
- Test: `backend/tests/test_plugin_base.py`

- [ ] **Step 1: Write the failing test**

```python
import datetime as dt

import pytest

from app.plugins.base import (
    CrawledFile,
    CrawlResult,
    DirectLink,
    LinkDead,
    PluginError,
    RateLimited,
    UnsupportedLink,
)


def test_crawl_result_defaults_to_empty():
    result = CrawlResult()
    assert result.files == []
    assert result.children == []


def test_crawled_file_defaults_to_alive_with_unknown_size():
    f = CrawledFile(url="http://x/a.zip", filename="a.zip")
    assert f.size is None
    assert f.alive is True


def test_direct_link_defaults_to_no_extra_headers():
    assert DirectLink(url="http://x/a.zip").headers == {}


def test_every_plugin_failure_is_a_plugin_error():
    # The scheduler and the crawler each catch PluginError once. If these were
    # not a single family, every call site would need to list them all and a
    # new exception type would silently escape into the loop.
    assert issubclass(LinkDead, PluginError)
    assert issubclass(UnsupportedLink, PluginError)
    assert issubclass(RateLimited, PluginError)


def test_rate_limited_carries_when_to_retry():
    when = dt.datetime(2026, 8, 8, 15, 42, tzinfo=dt.timezone.utc)
    exc = RateLimited(retry_at=when)
    assert exc.retry_at == when
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_base.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.plugins'`

- [ ] **Step 3: Create the package marker**

Create `backend/app/plugins/__init__.py` as an empty file.

- [ ] **Step 4: Implement `backend/app/plugins/base.py`**

```python
"""El contrato que todo hoster implementa. Sin I/O: solo tipos y errores."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CrawledFile:
    """Un archivo concreto descubierto detrás de un link."""

    url: str
    filename: str
    #: None cuando el hoster no informa tamaño hasta el momento de bajar.
    size: int | None = None
    alive: bool = True


@dataclass(frozen=True)
class CrawlResult:
    """Lo que hay detrás de un link: archivos, y links que aún hay que abrir."""

    files: list[CrawledFile] = field(default_factory=list)
    #: Links descubiertos que a su vez deben crawlearse (carpeta dentro de carpeta).
    children: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DirectLink:
    """URL descargable ya materializada, válida por poco tiempo."""

    url: str
    #: Cookies, referer o lo que esa URL exija para no devolver 403.
    headers: dict[str, str] = field(default_factory=dict)


class PluginError(Exception):
    """Raíz de todo fallo de plugin.

    Cada call site captura esta clase una sola vez. Si las variantes de abajo
    no compartieran raíz, agregar una nueva exigiría tocar cada call site y,
    mientras tanto, escaparía al loop.
    """


class LinkDead(PluginError):
    """El archivo ya no existe. No se reintenta: no va a revivir."""


class UnsupportedLink(PluginError):
    """Este plugin no sabe manejar esta URL; que siga probando el registro."""


class RateLimited(PluginError):
    """El hoster pide esperar. No es un fallo, es trabajo agendado."""

    def __init__(self, retry_at: dt.datetime, message: str = "rate limited"):
        super().__init__(message)
        self.retry_at = retry_at


@runtime_checkable
class Hoster(Protocol):
    """Las dos operaciones son distintas y ocurren en momentos distintos.

    `crawl` corre al agregar el link y descubre qué archivos hay detrás.
    `resolve` corre justo antes de descargar y devuelve la URL directa.

    Están separadas porque las URLs directas caducan: casi todo hoster las
    firma con un token de un solo uso o con TTL de minutos, así que resolver
    todo al agregar dejaría una cola de 40 archivos con 39 URLs vencidas
    antes de llegar a ellas.
    """

    name: str

    def can_handle(self, url: str) -> bool: ...

    async def crawl(self, url: str) -> CrawlResult: ...

    async def resolve(self, url: str) -> DirectLink: ...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_base.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/plugins backend/tests/test_plugin_base.py
git commit -m "feat: add the hoster plugin contract and typed errors"
```

---

## Task 2: Plugin `direct` (fallback)

**Files:**
- Create: `backend/app/plugins/direct.py`
- Test: `backend/tests/test_plugin_direct.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from app.plugins.direct import PLUGIN


def test_direct_handles_any_url():
    # Es la red de seguridad del registro: si no matchea nadie más, matchea este.
    assert PLUGIN.can_handle("http://example.com/a.zip")
    assert PLUGIN.can_handle("https://whatever/x")


@pytest.mark.asyncio
async def test_direct_crawl_reports_the_url_as_a_single_file():
    result = await PLUGIN.crawl("http://example.com/path/a.zip")

    assert result.children == []
    assert len(result.files) == 1
    assert result.files[0].url == "http://example.com/path/a.zip"
    assert result.files[0].filename == "a.zip"
    # El tamaño lo averigua el probe HEAD del motor, no este plugin: hacer
    # una request extra acá duplicaría la que el downloader ya hace igual.
    assert result.files[0].size is None


@pytest.mark.asyncio
async def test_direct_crawl_falls_back_to_a_usable_filename():
    result = await PLUGIN.crawl("http://example.com/")
    assert result.files[0].filename == "download"


@pytest.mark.asyncio
async def test_direct_resolve_returns_the_url_unchanged():
    link = await PLUGIN.resolve("http://example.com/a.zip")
    assert link.url == "http://example.com/a.zip"
    assert link.headers == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_direct.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.plugins.direct'`

- [ ] **Step 3: Implement `backend/app/plugins/direct.py`**

```python
"""Enlace directo: la URL pegada ya es descargable.

Existe como plugin en vez de como caso especial para que el resto del código
nunca tenga que ramificar entre "con plugin" y "sin plugin".
"""

from app.plugins.base import CrawledFile, CrawlResult, DirectLink


def filename_from_url(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name or "download"


class DirectHoster:
    name = "direct"

    def can_handle(self, url: str) -> bool:
        return True  # el registro lo consulta último, así que esto es el fallback

    async def crawl(self, url: str) -> CrawlResult:
        return CrawlResult(files=[CrawledFile(url=url, filename=filename_from_url(url))])

    async def resolve(self, url: str) -> DirectLink:
        return DirectLink(url=url)


PLUGIN = DirectHoster()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_direct.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/plugins/direct.py backend/tests/test_plugin_direct.py
git commit -m "feat: add the direct-link fallback plugin"
```

---

## Task 3: Registro de plugins con descubrimiento, timeout y normalización de errores

**Files:**
- Create: `backend/app/plugins/registry.py`
- Test: `backend/tests/test_plugin_registry.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from app.plugins.base import CrawlResult, DirectLink, PluginError, UnsupportedLink
from app.plugins.registry import (
    PLUGIN_TIMEOUT_SECONDS,
    Registry,
    call_crawl,
    call_resolve,
    discover,
)


class FakeHoster:
    def __init__(self, name, prefix, crawl_impl=None, resolve_impl=None):
        self.name = name
        self._prefix = prefix
        self._crawl_impl = crawl_impl
        self._resolve_impl = resolve_impl

    def can_handle(self, url):
        return url.startswith(self._prefix)

    async def crawl(self, url):
        if self._crawl_impl:
            return await self._crawl_impl(url)
        return CrawlResult()

    async def resolve(self, url):
        if self._resolve_impl:
            return await self._resolve_impl(url)
        return DirectLink(url=url)


def test_discovery_finds_the_shipped_plugins():
    names = {p.name for p in discover()}
    assert {"direct", "open_directory", "pixeldrain"} <= names


def test_direct_is_always_last_so_it_never_shadows_a_real_hoster():
    # can_handle de direct devuelve True para todo. Si quedara primero, ningún
    # otro plugin se usaría jamás.
    assert discover()[-1].name == "direct"


def test_find_returns_the_first_matching_plugin():
    a = FakeHoster("a", "http://a/")
    fallback = FakeHoster("direct", "")
    registry = Registry([a, fallback])

    assert registry.find("http://a/x").name == "a"
    assert registry.find("http://zzz/x").name == "direct"


def test_get_looks_a_plugin_up_by_name():
    a = FakeHoster("a", "http://a/")
    registry = Registry([a])

    assert registry.get("a") is a
    assert registry.get("nope") is None


@pytest.mark.asyncio
async def test_a_hung_plugin_does_not_hold_its_slot_forever():
    async def never_returns(url):
        await asyncio.sleep(3600)

    plugin = FakeHoster("slow", "http://", crawl_impl=never_returns)

    # Sin timeout, unos pocos links contra un sitio caído congelan toda la cola:
    # cada uno retiene un slot de concurrencia de forma indefinida.
    with pytest.raises(PluginError, match="timed out"):
        await call_crawl(plugin, "http://x/a", timeout=0.05)


@pytest.mark.asyncio
async def test_an_unexpected_exception_is_normalized_to_plugin_error():
    async def explodes(url):
        raise ValueError("el sitio devolvió algo que no esperaba")

    plugin = FakeHoster("boom", "http://", crawl_impl=explodes)

    # Un plugin es código de terceros dentro del proceso. Dejar escapar una
    # excepción arbitraria mata el loop que lo llamó.
    with pytest.raises(PluginError, match="el sitio devolvió algo"):
        await call_crawl(plugin, "http://x/a")


@pytest.mark.asyncio
async def test_typed_plugin_errors_pass_through_unchanged():
    async def unsupported(url):
        raise UnsupportedLink("no es mío")

    plugin = FakeHoster("picky", "http://", crawl_impl=unsupported)

    # El registro las usa para decidir; envolverlas en PluginError perdería
    # esa información y un link soportado terminaría como error.
    with pytest.raises(UnsupportedLink):
        await call_crawl(plugin, "http://x/a")


@pytest.mark.asyncio
async def test_call_resolve_applies_the_same_guards():
    async def explodes(url):
        raise ValueError("boom")

    plugin = FakeHoster("boom", "http://", resolve_impl=explodes)

    with pytest.raises(PluginError):
        await call_resolve(plugin, "http://x/a")


def test_the_default_timeout_is_generous_enough_for_a_wait_timer():
    # Un hoster gratuito puede hacerte esperar; el timeout es contra plugins
    # colgados, no contra plugins lentos.
    assert PLUGIN_TIMEOUT_SECONDS >= 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.plugins.registry'`

- [ ] **Step 3: Implement `backend/app/plugins/registry.py`**

```python
"""Descubrimiento y ejecución protegida de plugins."""

import asyncio
import importlib
import logging
import pkgutil

from app.plugins.base import DirectLink, CrawlResult, Hoster, PluginError

logger = logging.getLogger(__name__)

#: Tope por llamada a un plugin. No es contra plugins lentos (un hoster puede
#: legítimamente hacerte esperar), es contra plugins colgados: sin tope, un
#: sitio caído retiene un slot de concurrencia para siempre.
PLUGIN_TIMEOUT_SECONDS = 120.0

#: Va último en el orden de matching: su can_handle devuelve True para todo.
_FALLBACK_NAME = "direct"


class Registry:
    def __init__(self, plugins: list[Hoster]):
        self._plugins = plugins

    def find(self, url: str) -> Hoster:
        for plugin in self._plugins:
            if plugin.can_handle(url):
                return plugin
        raise PluginError(f"ningún plugin acepta {url}")  # imposible con direct presente

    def get(self, name: str) -> Hoster | None:
        for plugin in self._plugins:
            if plugin.name == name:
                return plugin
        return None

    def names(self) -> list[str]:
        return [p.name for p in self._plugins]


def discover() -> list[Hoster]:
    """Carga todo módulo de app.plugins que exponga PLUGIN.

    Agregar un hoster es agregar un archivo: no hay lista que mantener, que es
    lo que hace barato arreglar un plugin roto.
    """
    import app.plugins as package

    found: list[Hoster] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        plugin = getattr(module, "PLUGIN", None)
        if plugin is not None:
            found.append(plugin)

    found.sort(key=lambda p: p.name == _FALLBACK_NAME)
    return found


async def call_crawl(plugin: Hoster, url: str, timeout: float = PLUGIN_TIMEOUT_SECONDS) -> CrawlResult:
    return await _guard(plugin.crawl(url), plugin=plugin, url=url, timeout=timeout)


async def call_resolve(plugin: Hoster, url: str, timeout: float = PLUGIN_TIMEOUT_SECONDS) -> DirectLink:
    return await _guard(plugin.resolve(url), plugin=plugin, url=url, timeout=timeout)


async def _guard(coro, *, plugin: Hoster, url: str, timeout: float):
    """Acota el tiempo y normaliza cualquier fallo no tipado a PluginError.

    Las excepciones tipadas pasan intactas: el registro y el scheduler las
    usan para decidir (seguir probando, reagendar, marcar muerto), y
    envolverlas perdería esa decisión.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except PluginError:
        raise
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise PluginError(f"{plugin.name} timed out after {timeout}s on {url}") from exc
    except Exception as exc:  # noqa: BLE001 - código de terceros dentro del proceso
        logger.exception("plugin %s failed on %s", plugin.name, url)
        raise PluginError(f"{plugin.name}: {exc}") from exc


registry = Registry(discover())
```

- [ ] **Step 4: Run test to verify it fails on the two shipped-plugin tests only**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_registry.py -q`
Expected: FAIL — 2 fallos (`test_discovery_finds_the_shipped_plugins`, `test_direct_is_always_last...` puede pasar) porque `open_directory` y `pixeldrain` aún no existen. El resto PASS. Se completan en las tareas 4 y 5.

- [ ] **Step 5: Commit**

```bash
git add backend/app/plugins/registry.py backend/tests/test_plugin_registry.py
git commit -m "feat: add the plugin registry with discovery, timeout and error normalization"
```

---

## Task 4: Plugin `open_directory` (expansión de carpetas)

**Files:**
- Create: `backend/app/plugins/open_directory.py`
- Create: `backend/tests/fixtures/pages/nginx_autoindex.html`
- Test: `backend/tests/test_plugin_open_directory.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add the HTML parser dependency**

En `backend/pyproject.toml`, dentro de `dependencies`, agregar después de `"websockets>=12.0",`:

```toml
    # Parser HTML para los plugins. selectolax sobre bs4: es C puro, no arrastra
    # soup-sieve/lxml, y el parseo ocurre dentro del loop de crawl.
    "selectolax>=0.3.21",
```

Run: `cd backend && ./.venv/Scripts/python.exe -m pip install -q -e ".[dev]"`

- [ ] **Step 2: Create the saved page fixture**

Create `backend/tests/fixtures/pages/nginx_autoindex.html`:

```html
<html>
<head><title>Index of /media/</title></head>
<body>
<h1>Index of /media/</h1><hr><pre><a href="../">../</a>
<a href="subdir/">subdir/</a>                                          08-Aug-2026 12:01       -
<a href="ep01.mkv">ep01.mkv</a>                                        08-Aug-2026 12:02  734003200
<a href="ep02.mkv">ep02.mkv</a>                                        08-Aug-2026 12:03  702545920
<a href="notes.txt">notes.txt</a>                                      08-Aug-2026 12:04       1024
</pre><hr></body>
</html>
```

- [ ] **Step 3: Write the failing test**

```python
import pathlib

import httpx
import pytest

from app.plugins.base import LinkDead, UnsupportedLink
from app.plugins.open_directory import OpenDirectoryHoster

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "pages" / "nginx_autoindex.html"


def hoster_serving(body: str, status: int = 200, content_type: str = "text/html"):
    """Plugin cableado a una respuesta fija, sin tocar la red."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers={"Content-Type": content_type})

    return OpenDirectoryHoster(transport=httpx.MockTransport(handler))


def test_only_handles_urls_that_look_like_a_directory():
    plugin = OpenDirectoryHoster()
    assert plugin.can_handle("http://example.com/media/")
    assert not plugin.can_handle("http://example.com/media/ep01.mkv")


@pytest.mark.asyncio
async def test_crawl_lists_files_with_their_sizes():
    plugin = hoster_serving(FIXTURE.read_text())

    result = await plugin.crawl("http://example.com/media/")

    names = {f.filename: f for f in result.files}
    assert set(names) == {"ep01.mkv", "ep02.mkv", "notes.txt"}
    assert names["ep01.mkv"].url == "http://example.com/media/ep01.mkv"
    assert names["ep01.mkv"].size == 734003200


@pytest.mark.asyncio
async def test_crawl_reports_subdirectories_as_children_not_files():
    plugin = hoster_serving(FIXTURE.read_text())

    result = await plugin.crawl("http://example.com/media/")

    # El crawler los abre recursivamente; tratarlos como archivos encolaría
    # una descarga de una página HTML.
    assert result.children == ["http://example.com/media/subdir/"]


@pytest.mark.asyncio
async def test_crawl_ignores_the_parent_link():
    plugin = hoster_serving(FIXTURE.read_text())

    result = await plugin.crawl("http://example.com/media/")

    # "../" apunta hacia arriba: seguirlo saldría del árbol que el usuario
    # pidió y, con la recursión, podría volver a entrar por otro lado.
    assert all(not c.endswith("../") for c in result.children)


@pytest.mark.asyncio
async def test_a_missing_directory_is_dead_not_an_error():
    plugin = hoster_serving("not found", status=404)

    with pytest.raises(LinkDead):
        await plugin.crawl("http://example.com/gone/")


@pytest.mark.asyncio
async def test_a_non_html_response_is_not_ours():
    plugin = hoster_serving("{}", content_type="application/json")

    # Una URL con barra final que devuelve JSON es una API, no un autoindex.
    # Rechazarla deja que el registro caiga en direct en vez de inventar
    # archivos a partir de un cuerpo que no es una página.
    with pytest.raises(UnsupportedLink):
        await plugin.crawl("http://example.com/api/")


@pytest.mark.asyncio
async def test_resolve_returns_the_file_url_unchanged():
    plugin = OpenDirectoryHoster()
    link = await plugin.resolve("http://example.com/media/ep01.mkv")
    assert link.url == "http://example.com/media/ep01.mkv"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_open_directory.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.plugins.open_directory'`

- [ ] **Step 5: Implement `backend/app/plugins/open_directory.py`**

```python
"""Índices de directorio abiertos (autoindex de nginx/Apache).

Es el caso más simple de "un link contiene N archivos", y sirve de plantilla
para cualquier plugin que expanda una carpeta.
"""

import re
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.plugins.base import CrawledFile, CrawlResult, DirectLink, LinkDead, UnsupportedLink

#: El autoindex de nginx pone el tamaño al final de la línea, después de la fecha.
_SIZE_AT_END_OF_LINE = re.compile(r"(\d+)\s*$")


class OpenDirectoryHoster:
    name = "open_directory"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        # Inyectable para poder testear contra páginas guardadas sin red.
        self._transport = transport

    def can_handle(self, url: str) -> bool:
        return urlparse(url).path.endswith("/")

    async def crawl(self, url: str) -> CrawlResult:
        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.get(url)

        if response.status_code == 404:
            raise LinkDead(f"no existe: {url}")
        if response.status_code >= 400:
            raise UnsupportedLink(f"status {response.status_code} en {url}")
        if "html" not in response.headers.get("Content-Type", ""):
            raise UnsupportedLink(f"{url} no devuelve HTML")

        files: list[CrawledFile] = []
        children: list[str] = []

        for line in response.text.splitlines():
            node = HTMLParser(line).css_first("a")
            if node is None:
                continue
            href = node.attributes.get("href")
            if not href or href.startswith("?") or href.startswith("#"):
                continue

            absolute = urljoin(url, href)
            if not absolute.startswith(url):
                continue  # "../" y cualquier link que salga del árbol pedido

            if href.endswith("/"):
                children.append(absolute)
            else:
                files.append(
                    CrawledFile(
                        url=absolute,
                        filename=node.text().strip() or href,
                        size=_size_from(line),
                    )
                )

        return CrawlResult(files=files, children=children)

    async def resolve(self, url: str) -> DirectLink:
        # Un autoindex sirve el archivo en su propia URL: no hay nada que firmar.
        return DirectLink(url=url)


def _size_from(line: str) -> int | None:
    match = _SIZE_AT_END_OF_LINE.search(line.rstrip())
    return int(match.group(1)) if match else None


PLUGIN = OpenDirectoryHoster()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_open_directory.py -q`
Expected: PASS (7 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/app/plugins/open_directory.py backend/tests/test_plugin_open_directory.py backend/tests/fixtures/pages backend/pyproject.toml
git commit -m "feat: add the open-directory plugin that expands a folder into files"
```

---

## Task 5: Plugin `pixeldrain` (hoster real vía API)

**Files:**
- Create: `backend/app/plugins/pixeldrain.py`
- Test: `backend/tests/test_plugin_pixeldrain.py`

- [ ] **Step 1: Write the failing test**

```python
import json

import httpx
import pytest

from app.plugins.base import LinkDead
from app.plugins.pixeldrain import PixeldrainHoster


def hoster_with(routes: dict[str, tuple[int, dict]]):
    """routes: path -> (status, json body)."""

    def handler(request: httpx.Request) -> httpx.Response:
        status, body = routes.get(request.url.path, (404, {"success": False}))
        return httpx.Response(status, content=json.dumps(body), headers={"Content-Type": "application/json"})

    return PixeldrainHoster(transport=httpx.MockTransport(handler))


def test_handles_only_pixeldrain_urls():
    plugin = PixeldrainHoster()
    assert plugin.can_handle("https://pixeldrain.com/u/abc123")
    assert plugin.can_handle("https://pixeldrain.com/l/xyz789")
    assert not plugin.can_handle("https://example.com/u/abc123")


@pytest.mark.asyncio
async def test_crawl_of_a_single_file_reports_name_and_size():
    plugin = hoster_with({"/api/file/abc123/info": (200, {"name": "video.mkv", "size": 12345})})

    result = await plugin.crawl("https://pixeldrain.com/u/abc123")

    assert result.children == []
    assert len(result.files) == 1
    assert result.files[0].filename == "video.mkv"
    assert result.files[0].size == 12345
    assert result.files[0].url == "https://pixeldrain.com/u/abc123"


@pytest.mark.asyncio
async def test_crawl_of_an_album_expands_into_its_files():
    plugin = hoster_with(
        {
            "/api/list/xyz789": (
                200,
                {"files": [{"id": "f1", "name": "a.zip", "size": 10}, {"id": "f2", "name": "b.zip", "size": 20}]},
            )
        }
    )

    result = await plugin.crawl("https://pixeldrain.com/l/xyz789")

    assert [f.filename for f in result.files] == ["a.zip", "b.zip"]
    # Cada archivo apunta a su propia URL de archivo, no a la del álbum: el
    # motor descarga archivos, no colecciones.
    assert result.files[0].url == "https://pixeldrain.com/u/f1"


@pytest.mark.asyncio
async def test_a_deleted_file_is_dead():
    plugin = hoster_with({"/api/file/gone/info": (404, {"success": False, "message": "not found"})})

    with pytest.raises(LinkDead):
        await plugin.crawl("https://pixeldrain.com/u/gone")


@pytest.mark.asyncio
async def test_resolve_points_at_the_download_endpoint():
    plugin = PixeldrainHoster()

    link = await plugin.resolve("https://pixeldrain.com/u/abc123")

    # La página /u/ es HTML; el binario está en /api/file/{id}.
    assert link.url == "https://pixeldrain.com/api/file/abc123?download"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_pixeldrain.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.plugins.pixeldrain'`

- [ ] **Step 3: Implement `backend/app/plugins/pixeldrain.py`**

```python
"""Pixeldrain, vía su API JSON pública.

Sirve de plantilla para hosters con API documentada: no hay HTML que parsear,
así que no se rompe cuando el sitio cambia su maquetado.
"""

import re

import httpx

from app.plugins.base import CrawledFile, CrawlResult, DirectLink, LinkDead, PluginError

_BASE = "https://pixeldrain.com"
_FILE_URL = re.compile(r"^https?://(?:www\.)?pixeldrain\.com/u/(?P<id>[\w-]+)")
_LIST_URL = re.compile(r"^https?://(?:www\.)?pixeldrain\.com/l/(?P<id>[\w-]+)")


class PixeldrainHoster:
    name = "pixeldrain"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def can_handle(self, url: str) -> bool:
        return bool(_FILE_URL.match(url) or _LIST_URL.match(url))

    async def crawl(self, url: str) -> CrawlResult:
        list_match = _LIST_URL.match(url)
        if list_match:
            body = await self._get(f"{_BASE}/api/list/{list_match.group('id')}", url)
            return CrawlResult(
                files=[
                    # Cada entrada apunta a su propia URL de archivo: el motor
                    # descarga archivos, no colecciones.
                    CrawledFile(
                        url=f"{_BASE}/u/{entry['id']}",
                        filename=entry.get("name", entry["id"]),
                        size=entry.get("size"),
                    )
                    for entry in body.get("files", [])
                ]
            )

        file_match = _FILE_URL.match(url)
        if file_match is None:
            raise PluginError(f"URL de pixeldrain no reconocida: {url}")

        body = await self._get(f"{_BASE}/api/file/{file_match.group('id')}/info", url)
        return CrawlResult(
            files=[
                CrawledFile(
                    url=url,
                    filename=body.get("name", file_match.group("id")),
                    size=body.get("size"),
                )
            ]
        )

    async def resolve(self, url: str) -> DirectLink:
        match = _FILE_URL.match(url)
        if match is None:
            raise PluginError(f"no se puede descargar directamente {url}")
        # /u/ es la página HTML; el binario vive en el endpoint de la API.
        return DirectLink(url=f"{_BASE}/api/file/{match.group('id')}?download")

    async def _get(self, api_url: str, original_url: str) -> dict:
        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.get(api_url)

        if response.status_code in (404, 410):
            raise LinkDead(f"ya no existe: {original_url}")
        if response.status_code >= 400:
            raise PluginError(f"pixeldrain devolvió {response.status_code} para {original_url}")
        return response.json()


PLUGIN = PixeldrainHoster()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_plugin_pixeldrain.py tests/test_plugin_registry.py -q`
Expected: PASS — incluidos ahora los dos tests de descubrimiento de la Task 3

- [ ] **Step 5: Commit**

```bash
git add backend/app/plugins/pixeldrain.py backend/tests/test_plugin_pixeldrain.py
git commit -m "feat: add the pixeldrain plugin for single files and albums"
```

---

## Task 6: Modelos y migración

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0002_plugins.py`
- Test: `backend/tests/test_models_phase2.py`

- [ ] **Step 1: Write the failing test**

```python
import datetime as dt

import pytest
from sqlalchemy import select

from app.models import CrawlJob, CrawlResult, DownloadItem, GlobalSettings, Package


@pytest.mark.asyncio
async def test_crawl_job_holds_the_raw_pasted_text(session):
    job = CrawlJob(raw_input="http://a/x\nhttp://b/y")
    session.add(job)
    await session.commit()

    stored = (await session.execute(select(CrawlJob))).scalar_one()
    assert stored.status == "pending"
    assert stored.raw_input.splitlines() == ["http://a/x", "http://b/y"]
    assert stored.created_at is not None


@pytest.mark.asyncio
async def test_crawl_results_hang_off_their_job(session):
    job = CrawlJob(raw_input="http://a/x")
    session.add(job)
    await session.flush()
    session.add(
        CrawlResult(
            crawl_job_id=job.id, url="http://a/x", filename="x.zip", size=10, hoster="direct", status="ok"
        )
    )
    await session.commit()

    stored = (await session.execute(select(CrawlResult))).scalar_one()
    assert stored.crawl_job_id == job.id
    assert stored.status == "ok"


@pytest.mark.asyncio
async def test_download_items_record_their_hoster_and_have_no_wait_by_default(session, tmp_path):
    package = Package(name="p", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    item = DownloadItem(package_id=package.id, url="http://a/x", filename="x", hoster="direct")
    session.add(item)
    await session.commit()

    stored = (await session.execute(select(DownloadItem))).scalar_one()
    assert stored.hoster == "direct"
    # Sin espera pendiente el scheduler lo levanta de inmediato; ese es el caso normal.
    assert stored.retry_after is None


@pytest.mark.asyncio
async def test_settings_carry_a_crawl_concurrency_limit(session):
    session.add(GlobalSettings(id=1))
    await session.commit()

    row = (await session.execute(select(GlobalSettings))).scalar_one()
    # Más alto que el de descargas: crawlear es esperar respuestas cortas y no
    # satura ni disco ni ancho de banda.
    assert row.max_concurrent_crawls == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_models_phase2.py -q`
Expected: FAIL — `ImportError: cannot import name 'CrawlJob' from 'app.models'`

- [ ] **Step 3: Add the models to `backend/app/models.py`**

En `DownloadItem`, después de `retries: Mapped[int] = mapped_column(default=0)`, agregar:

```python
    #: Qué plugin resolvió este link, para saber a cuál llamar al descargar.
    #: Nunca nulo: un enlace directo queda como "direct".
    hoster: Mapped[str] = mapped_column(String(64), default="direct")
    #: Cuándo vuelve a ser elegible. El item sigue en "queued": para la cola es
    #: trabajo pendiente que todavía no toca, no un estado distinto.
    retry_after: Mapped[dt.datetime | None] = mapped_column(default=None)
```

En `GlobalSettings`, después de `max_speed_kbps`, agregar:

```python
    max_concurrent_crawls: Mapped[int] = mapped_column(default=5)
```

Al final del archivo, agregar:

```python
class CrawlJob(Base):
    """Un pegado de links esperando a que se descubra qué hay detrás."""

    __tablename__ = "crawl_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    raw_input: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    results: Mapped[list["CrawlResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class CrawlResult(Base):
    """Un archivo descubierto, todavía no encolado.

    OJO con el nombre: `app.plugins.base.CrawlResult` es otra cosa — el valor
    que devuelve un plugin (archivos + hijos a seguir). Este es la fila. Ningún
    módulo debe importar los dos; el puente entre ambos es `DiscoveredFile`.

    Qué se seleccionó no se guarda acá: vive en el cliente y viaja como lista
    de ids al confirmar. Persistirlo sería estado que mantener sincronizado
    sin que nadie lo consulte después.
    """

    __tablename__ = "crawl_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    crawl_job_id: Mapped[str] = mapped_column(ForeignKey("crawl_jobs.id"))
    url: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int | None] = mapped_column(default=None)
    hoster: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    job: Mapped["CrawlJob"] = relationship(back_populates="results")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_models_phase2.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Create `backend/alembic/versions/0002_plugins.py`**

```python
"""hoster plugins: crawl jobs, results, item hoster/retry_after, crawl concurrency

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('crawl_jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('raw_input', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('crawl_results',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('crawl_job_id', sa.String(length=36), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('filename', sa.String(length=1024), nullable=False),
    sa.Column('size', sa.Integer(), nullable=True),
    sa.Column('hoster', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['crawl_job_id'], ['crawl_jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # server_default en el add: las filas que ya existen necesitan un valor, y
    # todo lo descargado hasta ahora era un enlace directo.
    op.add_column('download_items', sa.Column('hoster', sa.String(length=64), nullable=False, server_default='direct'))
    op.add_column('download_items', sa.Column('retry_after', sa.DateTime(), nullable=True))
    op.add_column('settings', sa.Column('max_concurrent_crawls', sa.Integer(), nullable=False, server_default='5'))


def downgrade() -> None:
    op.drop_column('settings', 'max_concurrent_crawls')
    op.drop_column('download_items', 'retry_after')
    op.drop_column('download_items', 'hoster')
    op.drop_table('crawl_results')
    op.drop_table('crawl_jobs')
```

- [ ] **Step 6: Verify the migration applies against a real Postgres**

```bash
cd "$(git rev-parse --show-toplevel)"
cp .env.example .env
docker compose up -d postgres
docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://cascade:changeme@postgres:5432/cascade backend alembic upgrade head
```
Expected: `Running upgrade 0001 -> 0002, hoster plugins`

Cleanup: `docker compose down -v && rm .env`

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0002_plugins.py backend/tests/test_models_phase2.py
git commit -m "feat: add crawl job/result tables and item hoster + retry_after columns"
```

---

## Task 7: Núcleo del crawler (recursión acotada, sin DB)

**Files:**
- Create: `backend/app/crawler/__init__.py`
- Create: `backend/app/crawler/core.py`
- Test: `backend/tests/test_crawler_core.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from app.crawler.core import MAX_DEPTH, DiscoveredFile, crawl_link
from app.plugins.base import CrawledFile, CrawlResult, LinkDead, PluginError
from app.plugins.registry import Registry


class ScriptedHoster:
    """Devuelve lo que el test le dicta para cada URL."""

    name = "scripted"

    def __init__(self, script: dict):
        self._script = script

    def can_handle(self, url):
        return url in self._script

    async def crawl(self, url):
        outcome = self._script[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def resolve(self, url):
        raise AssertionError("crawl_link no debe resolver")


class NeverHandles:
    name = "direct"

    def can_handle(self, url):
        return True

    async def crawl(self, url):
        return CrawlResult(files=[CrawledFile(url=url, filename="fallback.bin")])

    async def resolve(self, url):
        raise AssertionError("crawl_link no debe resolver")


@pytest.mark.asyncio
async def test_a_plain_link_yields_one_file():
    registry = Registry([NeverHandles()])

    found = await crawl_link("http://x/a.zip", registry=registry)

    assert found == [
        DiscoveredFile(
            url="http://x/a.zip", filename="fallback.bin", size=None, hoster="direct",
            status="ok", error_message=None,
        )
    ]


@pytest.mark.asyncio
async def test_children_are_followed_recursively():
    registry = Registry([
        ScriptedHoster({
            "http://x/dir/": CrawlResult(children=["http://x/dir/sub/"]),
            "http://x/dir/sub/": CrawlResult(files=[CrawledFile(url="http://x/dir/sub/a.zip", filename="a.zip", size=5)]),
        }),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/dir/", registry=registry)

    assert [f.filename for f in found] == ["a.zip"]
    assert found[0].size == 5


@pytest.mark.asyncio
async def test_recursion_stops_at_the_depth_limit():
    # Una carpeta que se apunta a sí misma. Sin tope esto no termina nunca y
    # se come el slot de crawl para siempre.
    registry = Registry([
        ScriptedHoster({"http://x/loop/": CrawlResult(children=["http://x/loop/"])}),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/loop/", registry=registry, max_depth=2)

    assert found == []


@pytest.mark.asyncio
async def test_a_url_already_seen_is_not_crawled_twice():
    calls = []

    class Counting(ScriptedHoster):
        async def crawl(self, url):
            calls.append(url)
            return await super().crawl(url)

    registry = Registry([
        Counting({
            "http://x/a/": CrawlResult(children=["http://x/b/", "http://x/b/"]),
            "http://x/b/": CrawlResult(files=[CrawledFile(url="http://x/b/f", filename="f")]),
        }),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/a/", registry=registry)

    assert calls.count("http://x/b/") == 1
    assert len(found) == 1


@pytest.mark.asyncio
async def test_a_dead_link_is_reported_not_raised():
    registry = Registry([
        ScriptedHoster({"http://x/gone": LinkDead("ya no está")}),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/gone", registry=registry)

    # Un link muerto dentro de una lista de 40 no puede tumbar el crawl entero:
    # se informa como resultado para que el usuario vea qué se perdió.
    assert len(found) == 1
    assert found[0].status == "dead"
    assert found[0].url == "http://x/gone"


@pytest.mark.asyncio
async def test_a_plugin_failure_is_reported_as_an_error_result():
    registry = Registry([
        ScriptedHoster({"http://x/boom": PluginError("el sitio cambió")}),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/boom", registry=registry)

    assert found[0].status == "error"
    assert found[0].error_message == "el sitio cambió"


@pytest.mark.asyncio
async def test_a_dead_file_inside_a_folder_is_kept_as_dead():
    registry = Registry([
        ScriptedHoster({
            "http://x/d/": CrawlResult(files=[
                CrawledFile(url="http://x/d/ok", filename="ok"),
                CrawledFile(url="http://x/d/no", filename="no", alive=False),
            ])
        }),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/d/", registry=registry)

    assert {f.filename: f.status for f in found} == {"ok": "ok", "no": "dead"}


def test_the_default_depth_limit_is_small():
    assert MAX_DEPTH <= 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_crawler_core.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.crawler'`

- [ ] **Step 3: Create the package marker**

Create `backend/app/crawler/__init__.py` as an empty file.

- [ ] **Step 4: Implement `backend/app/crawler/core.py`**

```python
"""Descubre qué archivos hay detrás de un link. Sin DB: solo plugins."""

import logging
from dataclasses import dataclass

from app.plugins.base import LinkDead, PluginError
from app.plugins.registry import Registry, call_crawl, registry as default_registry

logger = logging.getLogger(__name__)

#: Cuán hondo se siguen carpetas dentro de carpetas. Bajo a propósito: un link
#: mal formado que se apunta a sí mismo es, sin tope, un bucle infinito.
MAX_DEPTH = 3


@dataclass(frozen=True)
class DiscoveredFile:
    url: str
    filename: str
    size: int | None
    hoster: str
    status: str  # "ok" | "dead" | "error"
    error_message: str | None


async def crawl_link(
    url: str,
    *,
    registry: Registry | None = None,
    max_depth: int = MAX_DEPTH,
) -> list[DiscoveredFile]:
    """Expande `url` en los archivos concretos que contiene.

    Nunca lanza por culpa de un link: un muerto o un plugin roto se devuelven
    como resultados con su estado, porque dentro de una lista de 40 links uno
    malo no puede tumbar el descubrimiento de los otros 39.
    """
    registry = registry or default_registry
    found: list[DiscoveredFile] = []
    seen: set[str] = set()
    pending: list[tuple[str, int]] = [(url, 0)]

    while pending:
        current, depth = pending.pop(0)
        if current in seen or depth > max_depth:
            continue
        seen.add(current)

        plugin = registry.find(current)
        try:
            result = await call_crawl(plugin, current)
        except LinkDead as exc:
            found.append(_failed(current, plugin.name, "dead", str(exc)))
            continue
        except PluginError as exc:
            found.append(_failed(current, plugin.name, "error", str(exc)))
            continue

        for discovered in result.files:
            found.append(
                DiscoveredFile(
                    url=discovered.url,
                    filename=discovered.filename,
                    size=discovered.size,
                    hoster=plugin.name,
                    status="ok" if discovered.alive else "dead",
                    error_message=None,
                )
            )

        pending.extend((child, depth + 1) for child in result.children)

    return found


def _failed(url: str, hoster: str, status: str, message: str) -> DiscoveredFile:
    return DiscoveredFile(
        url=url,
        filename=url.rstrip("/").rsplit("/", 1)[-1] or url,
        size=None,
        hoster=hoster,
        status=status,
        error_message=message,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_crawler_core.py -q`
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/crawler backend/tests/test_crawler_core.py
git commit -m "feat: add the crawler core with bounded recursion and per-link failure isolation"
```

---

## Task 8: Runner del crawler (persistencia de jobs y resultados)

**Files:**
- Create: `backend/app/crawler/runner.py`
- Test: `backend/tests/test_crawler_runner.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import select

from app.crawler.core import DiscoveredFile
from app.crawler.runner import run_pending_crawls
from app.models import CrawlJob, CrawlResult


@pytest.fixture
def fake_crawl(monkeypatch):
    """Reemplaza crawl_link por un guion, para no tocar la red."""
    import app.crawler.runner as runner

    script: dict[str, list[DiscoveredFile] | Exception] = {}

    async def _crawl(url, **kwargs):
        outcome = script[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(runner, "crawl_link", _crawl)
    return script


def a_file(url="http://x/a.zip", name="a.zip", status="ok"):
    return DiscoveredFile(url=url, filename=name, size=7, hoster="direct", status=status, error_message=None)


@pytest.mark.asyncio
async def test_a_pending_job_becomes_done_with_its_results(session, fake_crawl):
    fake_crawl["http://x/a.zip"] = [a_file()]
    session.add(CrawlJob(raw_input="http://x/a.zip"))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)

    job = (await session.execute(select(CrawlJob))).scalar_one()
    assert job.status == "done"
    results = (await session.execute(select(CrawlResult))).scalars().all()
    assert [r.filename for r in results] == ["a.zip"]
    assert results[0].hoster == "direct"


@pytest.mark.asyncio
async def test_every_line_of_the_paste_is_crawled(session, fake_crawl):
    fake_crawl["http://x/a"] = [a_file(url="http://x/a", name="a")]
    fake_crawl["http://x/b"] = [a_file(url="http://x/b", name="b")]
    session.add(CrawlJob(raw_input="http://x/a\n\n  http://x/b  \n"))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)

    results = (await session.execute(select(CrawlResult))).scalars().all()
    assert sorted(r.filename for r in results) == ["a", "b"]


@pytest.mark.asyncio
async def test_one_bad_link_does_not_sink_the_whole_job(session, fake_crawl):
    fake_crawl["http://x/ok"] = [a_file(url="http://x/ok", name="ok")]
    fake_crawl["http://x/bad"] = RuntimeError("algo raro")
    session.add(CrawlJob(raw_input="http://x/ok\nhttp://x/bad"))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)

    job = (await session.execute(select(CrawlJob))).scalar_one()
    assert job.status == "done"
    results = (await session.execute(select(CrawlResult))).scalars().all()
    by_name = {r.filename: r for r in results}
    assert by_name["ok"].status == "ok"
    assert by_name["bad"].status == "error"


@pytest.mark.asyncio
async def test_a_job_is_not_processed_twice(session, fake_crawl):
    calls = []

    async def counting(url, **kwargs):
        calls.append(url)
        return [a_file(url=url, name="x")]

    import app.crawler.runner as runner
    runner.crawl_link = counting

    session.add(CrawlJob(raw_input="http://x/a"))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)
    await run_pending_crawls(session, max_concurrent=2)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_only_max_concurrent_jobs_are_taken_per_pass(session, fake_crawl):
    for i in range(5):
        fake_crawl[f"http://x/{i}"] = [a_file(url=f"http://x/{i}", name=str(i))]
        session.add(CrawlJob(raw_input=f"http://x/{i}"))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)

    done = (await session.execute(select(CrawlJob).where(CrawlJob.status == "done"))).scalars().all()
    assert len(done) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_crawler_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.crawler.runner'`

- [ ] **Step 3: Implement `backend/app/crawler/runner.py`**

```python
"""Toma crawl_jobs pendientes y escribe sus resultados."""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.core import crawl_link
from app.models import CrawlJob, CrawlResult

logger = logging.getLogger(__name__)


async def run_pending_crawls(db: AsyncSession, max_concurrent: int) -> None:
    """Procesa hasta `max_concurrent` jobs pendientes.

    Igual que run_pending del scheduler, comparte una sola sesión y serializa
    todo acceso a DB con un lock creado por llamada. Vale la misma
    precondición: hay que await-earla hasta el final antes de volver a
    llamarla contra la misma sesión.
    """
    db_lock = asyncio.Lock()

    result = await db.execute(
        select(CrawlJob).where(CrawlJob.status == "pending").limit(max_concurrent)
    )
    jobs = result.scalars().all()
    if not jobs:
        return

    async with db_lock:
        for job in jobs:
            job.status = "running"
        await db.commit()

    await asyncio.gather(*(_run_one_job(db, db_lock, job) for job in jobs))


async def _run_one_job(db: AsyncSession, db_lock: asyncio.Lock, job: CrawlJob) -> None:
    links = [line.strip() for line in job.raw_input.splitlines() if line.strip()]
    discovered = []

    for link in links:
        try:
            discovered.extend(await crawl_link(link))
        except Exception as exc:  # noqa: BLE001 - un link malo no hunde el job
            # crawl_link ya absorbe los fallos de plugin; esto cubre lo que
            # ocurra fuera de ellos y evita que el gather aborte los otros jobs.
            logger.exception("crawl of %s failed", link)
            discovered.append(_error_row(link, str(exc)))

    async with db_lock:
        for found in discovered:
            db.add(
                CrawlResult(
                    crawl_job_id=job.id,
                    url=found.url,
                    filename=found.filename,
                    size=found.size,
                    hoster=found.hoster,
                    status=found.status,
                    error_message=found.error_message,
                )
            )
        job.status = "done"
        await db.commit()


def _error_row(url: str, message: str):
    from app.crawler.core import DiscoveredFile

    return DiscoveredFile(
        url=url,
        filename=url.rstrip("/").rsplit("/", 1)[-1] or url,
        size=None,
        hoster="direct",
        status="error",
        error_message=message,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_crawler_runner.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/crawler/runner.py backend/tests/test_crawler_runner.py
git commit -m "feat: add the crawl runner that persists discovered files per job"
```

---

## Task 9: Endpoints del grabber

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/app/api/crawl_jobs.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_crawl_jobs.py`

- [ ] **Step 1: Add an async HTTP client fixture to `backend/tests/conftest.py`**

Estos tests necesitan sembrar filas con la sesión async **y** llamar a la API en el mismo test. El `TestClient` síncrono de Fase 1 no sirve para eso: mezclarlo con una sesión async obliga a manejar dos loops y termina en deadlock o en un engine atado al loop equivocado.

Agregar al final del archivo:

```python
import httpx


@pytest_asyncio.fixture
async def async_client(db_engine):
    """Cliente HTTP sobre la app, usable desde un test async.

    ASGITransport no corre el lifespan, así que ni el scheduler ni el loop de
    crawl arrancan durante estos tests.
    """
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def async_auth_client(async_client):
    await async_client.post("/auth/login", json={"username": "admin", "password": "hunter2"})
    return async_client
```

- [ ] **Step 2: Write the failing test**

```python
import pytest

from app.models import CrawlResult


@pytest.mark.asyncio
async def test_creating_a_job_returns_it_pending(async_auth_client):
    response = await async_auth_client.post(
        "/crawl-jobs", json={"links": "http://x/a.zip\nhttp://x/b.zip"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["results"] == []


@pytest.mark.asyncio
async def test_creating_a_job_requires_at_least_one_link(async_auth_client):
    # min_length=1 por sí solo dejaría pasar un textarea con solo espacios y
    # produciría un job que no descubre nada, sin decir por qué.
    response = await async_auth_client.post("/crawl-jobs", json={"links": "   \n\n  "})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_listing_jobs_returns_newest_first(async_auth_client):
    await async_auth_client.post("/crawl-jobs", json={"links": "http://x/1"})
    await async_auth_client.post("/crawl-jobs", json={"links": "http://x/2"})

    body = (await async_auth_client.get("/crawl-jobs")).json()

    assert [j["raw_input"] for j in body] == ["http://x/2", "http://x/1"]


@pytest.mark.asyncio
async def test_fetching_an_unknown_job_is_404(async_auth_client):
    assert (await async_auth_client.get("/crawl-jobs/nope")).status_code == 404


@pytest.mark.asyncio
async def test_endpoints_require_authentication(async_client):
    assert (await async_client.post("/crawl-jobs", json={"links": "http://x/a"})).status_code == 401
    assert (await async_client.get("/crawl-jobs")).status_code == 401


@pytest.mark.asyncio
async def test_promoting_selected_results_creates_a_package(async_auth_client, session):
    created = await async_auth_client.post("/crawl-jobs", json={"links": "http://x/a.zip"})
    job_id = created.json()["id"]

    session.add_all([
        CrawlResult(id="r1", crawl_job_id=job_id, url="http://x/a.zip", filename="a.zip",
                    size=10, hoster="direct", status="ok"),
        CrawlResult(id="r2", crawl_job_id=job_id, url="http://x/b.zip", filename="b.zip",
                    size=20, hoster="pixeldrain", status="ok"),
    ])
    await session.commit()

    response = await async_auth_client.post(
        f"/crawl-jobs/{job_id}/promote", json={"name": "Mi paquete", "result_ids": ["r2"]}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Mi paquete"
    # Solo lo seleccionado. Encolar lo no elegido convierte la bandeja en decorado.
    assert [i["filename"] for i in body["items"]] == ["b.zip"]
    assert body["items"][0]["hoster"] == "pixeldrain"
    assert body["items"][0]["total_size"] == 20


@pytest.mark.asyncio
async def test_the_promoted_package_lands_under_the_download_root(async_auth_client, session):
    created = await async_auth_client.post("/crawl-jobs", json={"links": "http://x/a.zip"})
    job_id = created.json()["id"]
    session.add(CrawlResult(id="r1", crawl_job_id=job_id, url="http://x/a.zip", filename="a.zip",
                            size=10, hoster="direct", status="ok"))
    await session.commit()

    body = (await async_auth_client.post(
        f"/crawl-jobs/{job_id}/promote", json={"name": "p", "result_ids": ["r1"]}
    )).json()

    # Derivado del id generado, no del nombre que escribió el usuario: un nombre
    # con "../" escaparía del volumen de descargas.
    assert body["target_dir"].endswith(body["id"])


@pytest.mark.asyncio
async def test_promoting_nothing_is_rejected(async_auth_client):
    created = await async_auth_client.post("/crawl-jobs", json={"links": "http://x/a.zip"})
    job_id = created.json()["id"]

    response = await async_auth_client.post(
        f"/crawl-jobs/{job_id}/promote", json={"name": "p", "result_ids": []}
    )

    assert response.status_code == 422
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_api_crawl_jobs.py -q`
Expected: FAIL — 404 en todos los endpoints (el router no existe)

- [ ] **Step 4: Add the schemas to `backend/app/schemas.py`**

Al final del archivo:

```python
class CreateCrawlJobRequest(BaseModel):
    links: str = Field(min_length=1)

    @field_validator("links")
    @classmethod
    def at_least_one_link(cls, value: str) -> str:
        # min_length=1 dejaría pasar un textarea con solo espacios y produciría
        # un job que no descubre nada, sin decirle al usuario por qué.
        if not [line for line in value.splitlines() if line.strip()]:
            raise ValueError("hace falta al menos un enlace")
        return value


class CrawlResultResponse(BaseModel):
    id: str
    url: str
    filename: str
    size: int | None
    hoster: str
    status: str
    error_message: str | None

    model_config = {"from_attributes": True}


class CrawlJobResponse(BaseModel):
    id: str
    raw_input: str
    status: str
    error_message: str | None
    results: list[CrawlResultResponse]

    model_config = {"from_attributes": True}


class PromoteRequest(BaseModel):
    name: str = Field(min_length=1)
    result_ids: list[str] = Field(min_length=1)
```

Y en el import de pydantic al principio del archivo, cambiar:

```python
from pydantic import BaseModel, Field
```

por:

```python
from pydantic import BaseModel, Field, field_validator
```

Además, en `DownloadItemResponse`, agregar después de `error_message: str | None`:

```python
    hoster: str
    retry_after: dt.datetime | None
```

y al principio del archivo agregar `import datetime as dt`.

- [ ] **Step 5: Implement `backend/app/api/crawl_jobs.py`**

```python
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.config import Settings
from app.database import get_db
from app.models import CrawlJob, CrawlResult, DownloadItem, Package, User
from app.schemas import CrawlJobResponse, CreateCrawlJobRequest, PackageResponse, PromoteRequest
from app.settings_store import read_settings

router = APIRouter(prefix="/crawl-jobs", tags=["crawl"])
_settings = Settings()


@router.post("", response_model=CrawlJobResponse, status_code=status.HTTP_201_CREATED)
async def create_crawl_job(
    payload: CreateCrawlJobRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    job = CrawlJob(raw_input=payload.links)
    db.add(job)
    await db.commit()

    result = await db.execute(
        select(CrawlJob).options(selectinload(CrawlJob.results)).where(CrawlJob.id == job.id)
    )
    return result.scalar_one()


@router.get("", response_model=list[CrawlJobResponse])
async def list_crawl_jobs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CrawlJob).options(selectinload(CrawlJob.results)).order_by(CrawlJob.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{job_id}", response_model=CrawlJobResponse)
async def get_crawl_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CrawlJob).options(selectinload(CrawlJob.results)).where(CrawlJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return job


@router.post("/{job_id}/promote", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def promote(
    job_id: str,
    payload: PromoteRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Convierte los resultados elegidos en un paquete descargable.

    La copia es deliberada: los crawl_results son un hallazgo, los
    download_items son trabajo comprometido. Mantenerlos separados es lo que
    deja al scheduler con su contrato simple ("un item en queued es algo para
    bajar") en vez de tener que filtrar filas a medio resolver.
    """
    result = await db.execute(
        select(CrawlResult).where(
            CrawlResult.crawl_job_id == job_id, CrawlResult.id.in_(payload.result_ids)
        )
    )
    chosen = result.scalars().all()
    if not chosen:
        raise HTTPException(status_code=404, detail="No matching crawl results")

    root = await _download_root(db)
    package = Package(name=payload.name, status="queued", target_dir="")
    db.add(package)
    await db.flush()  # populates package.id
    package.target_dir = os.path.join(root, package.id)

    for found in chosen:
        db.add(
            DownloadItem(
                package_id=package.id,
                url=found.url,
                filename=found.filename,
                total_size=found.size,
                hoster=found.hoster,
                status="queued",
            )
        )

    await db.commit()

    created = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.id == package.id)
    )
    return created.scalar_one()


async def _download_root(db: AsyncSession) -> str:
    row = await read_settings(db)
    return row.download_root if row is not None else _settings.download_root
```

- [ ] **Step 6: Register the router in `backend/app/main.py`**

Agregar el import después de `from app.api.auth import router as auth_router`:

```python
from app.api.crawl_jobs import router as crawl_jobs_router
```

y después de `app.include_router(auth_router)`:

```python
app.include_router(crawl_jobs_router)
```

- [ ] **Step 7: Set `hoster` on the classic endpoint too**

En `backend/app/api/packages.py`, dentro de `create_package`, en la construcción de `DownloadItem`, agregar `hoster="direct",` después de `status="queued",`. Sin esto, un paquete creado por el endpoint clásico quedaría con el default del modelo y el origen del item sería implícito.

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_api_crawl_jobs.py -q`
Expected: PASS (7 passed)

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/crawl_jobs.py backend/app/schemas.py backend/app/main.py backend/app/api/packages.py backend/tests/test_api_crawl_jobs.py
git commit -m "feat: add crawl job endpoints and promotion to a download package"
```

---

## Task 10: Headers extra en el downloader

**Files:**
- Modify: `backend/app/engine/downloader.py`
- Modify: `backend/app/engine/item_runner.py`
- Test: `backend/tests/test_download_headers.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from app.engine.downloader import download_chunk
from app.engine.item_runner import run_download_item


@pytest.mark.asyncio
async def test_chunk_requests_carry_the_plugin_headers(test_server, tmp_path):
    payload = b"A" * 100
    server, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    await download_chunk(
        url=url, start=0, end=99, dest_path=str(dest), headers={"Cookie": "session=abc"}
    )

    # Muchos hosters devuelven 403 si falta la cookie o el referer que su URL
    # firmada espera; sin esto la descarga fallaría después de resolver bien.
    assert server.seen_headers[-1].get("Cookie") == "session=abc"


@pytest.mark.asyncio
async def test_plugin_headers_do_not_clobber_the_range_header(test_server, tmp_path):
    payload = b"B" * 100
    server, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    await download_chunk(
        url=url, start=10, end=49, dest_path=str(dest), headers={"Range": "bytes=0-999"}
    )

    # Range lo manda el motor de chunks. Que un plugin lo pise rompería la
    # descarga segmentada de forma silenciosa: el archivo quedaría corrupto.
    assert server.requested_ranges[-1] == (10, 49)


@pytest.mark.asyncio
async def test_the_probe_also_carries_the_headers(test_server, tmp_path):
    payload = b"C" * 200
    server, url = await test_server(payload)

    await run_download_item(
        url=url, dest_path=str(tmp_path / "out.bin"), num_chunks=1, headers={"Referer": "http://x/"}
    )

    assert any(h.get("Referer") == "http://x/" for h in server.seen_headers)
```

- [ ] **Step 2: Record request headers in the test server**

En `backend/tests/fixtures/test_server.py`, dentro de `__init__`, después de `self.requested_ranges: list[tuple[int, int]] = []`:

```python
        #: Headers de cada request servida, para poder afirmar qué mandó el motor.
        self.seen_headers: list[dict[str, str]] = []
```

Y como primera línea de `_handle` y de `_handle_head`:

```python
        self.seen_headers.append(dict(request.headers))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_download_headers.py -q`
Expected: FAIL — `TypeError: download_chunk() got an unexpected keyword argument 'headers'`

- [ ] **Step 4: Accept headers in `backend/app/engine/downloader.py`**

En la firma de `download_chunk`, después de `rate_limiter: RateLimiter | None = None,`:

```python
    headers: dict[str, str] | None = None,
```

Y reemplazar la línea `headers = {"Range": f"bytes={range_start}-{end}"}` por:

```python
                # El Range va último a propósito: lo calcula el motor de chunks,
                # y que un plugin lo pise corrompería el archivo en silencio.
                request_headers = {**(headers or {}), "Range": f"bytes={range_start}-{end}"}
```

y cambiar la llamada `client.stream("GET", url, headers=headers)` por `client.stream("GET", url, headers=request_headers)`.

- [ ] **Step 5: Propagate them in `backend/app/engine/item_runner.py`**

Cambiar la firma de `_probe`:

```python
async def _probe(url: str, headers: dict[str, str] | None = None) -> tuple[int, bool]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.head(url, headers=headers or {})
```

En la firma de `run_download_item`, después de `rate_limiter: RateLimiter | None = None,`:

```python
    headers: dict[str, str] | None = None,
```

Cambiar `total_size, supports_range = await _probe(url)` por:

```python
    total_size, supports_range = await _probe(url, headers)
```

Y en la llamada a `download_chunk` dentro de `_run_chunk`, agregar después de `rate_limiter=rate_limiter,`:

```python
            headers=headers,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_download_headers.py -q`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/app/engine/downloader.py backend/app/engine/item_runner.py backend/tests/fixtures/test_server.py backend/tests/test_download_headers.py
git commit -m "feat: carry plugin-supplied headers through the probe and every chunk"
```

---

## Task 11: El scheduler resuelve con plugins y respeta esperas

**Files:**
- Modify: `backend/app/engine/scheduler.py`
- Test: `backend/tests/test_scheduler_plugins.py`

- [ ] **Step 1: Write the failing test**

```python
import datetime as dt

import pytest
from sqlalchemy import select

from app.engine.scheduler import run_pending
from app.models import DownloadItem, Package
from app.plugins.base import DirectLink, LinkDead, RateLimited


async def one_item(session, tmp_path, url, **item_kwargs):
    package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    item = DownloadItem(
        package_id=package.id, url=url, filename="out.bin", status="queued",
        hoster="fake", **item_kwargs
    )
    session.add(item)
    await session.commit()
    return item


@pytest.mark.asyncio
async def test_the_resolver_supplies_the_url_that_is_actually_downloaded(session, test_server, tmp_path):
    payload = b"R" * 300
    _, real_url = await test_server(payload)
    item = await one_item(session, tmp_path, "http://placeholder/hidden")

    async def resolver(url, hoster):
        assert url == "http://placeholder/hidden"
        assert hoster == "fake"
        return DirectLink(url=real_url)

    await run_pending(session, max_concurrent=1, chunks_per_file=2, resolver=resolver)

    await session.refresh(item)
    assert item.status == "completed"
    assert (tmp_path / "out.bin").read_bytes() == payload


@pytest.mark.asyncio
async def test_a_rate_limited_item_is_rescheduled_not_failed(session, test_server, tmp_path):
    item = await one_item(session, tmp_path, "http://x/a")
    when = dt.datetime.utcnow() + dt.timedelta(minutes=30)

    async def resolver(url, hoster):
        raise RateLimited(retry_at=when)

    await run_pending(session, max_concurrent=1, chunks_per_file=2, resolver=resolver)

    await session.refresh(item)
    # Sigue siendo trabajo pendiente, no un fallo: marcarlo error obligaría al
    # usuario a reencolarlo a mano cada vez que un hoster gratuito pide esperar.
    assert item.status == "queued"
    assert item.error_message is None
    assert item.retry_after is not None


@pytest.mark.asyncio
async def test_an_item_waiting_is_skipped_until_its_time(session, test_server, tmp_path):
    started = []
    await one_item(
        session, tmp_path, "http://x/a", retry_after=dt.datetime.utcnow() + dt.timedelta(hours=1)
    )

    async def resolver(url, hoster):
        raise AssertionError("no debería haberse levantado")

    await run_pending(
        session, max_concurrent=5, chunks_per_file=2, resolver=resolver,
        _on_start_for_test=started.append,
    )

    assert started == []


@pytest.mark.asyncio
async def test_an_item_whose_wait_expired_is_picked_up(session, test_server, tmp_path):
    payload = b"W" * 100
    _, real_url = await test_server(payload)
    item = await one_item(
        session, tmp_path, "http://x/a", retry_after=dt.datetime.utcnow() - dt.timedelta(minutes=1)
    )

    async def resolver(url, hoster):
        return DirectLink(url=real_url)

    await run_pending(session, max_concurrent=1, chunks_per_file=1, resolver=resolver)

    await session.refresh(item)
    assert item.status == "completed"


@pytest.mark.asyncio
async def test_a_dead_link_fails_the_item_with_its_reason(session, test_server, tmp_path):
    item = await one_item(session, tmp_path, "http://x/gone")

    async def resolver(url, hoster):
        raise LinkDead("el archivo fue borrado")

    await run_pending(session, max_concurrent=1, chunks_per_file=2, resolver=resolver)

    await session.refresh(item)
    assert item.status == "error"
    assert "borrado" in item.error_message


@pytest.mark.asyncio
async def test_resolved_headers_reach_the_request(session, test_server, tmp_path):
    payload = b"H" * 120
    server, real_url = await test_server(payload)
    await one_item(session, tmp_path, "http://x/a")

    async def resolver(url, hoster):
        return DirectLink(url=real_url, headers={"Cookie": "s=1"})

    await run_pending(session, max_concurrent=1, chunks_per_file=1, resolver=resolver)

    assert any(h.get("Cookie") == "s=1" for h in server.seen_headers)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_scheduler_plugins.py -q`
Expected: FAIL — `TypeError: run_pending() got an unexpected keyword argument 'resolver'`

- [ ] **Step 3: Replace `identity` with `resolver` in `backend/app/engine/scheduler.py`**

Cambiar los imports del principio, agregando:

```python
import datetime as dt
from typing import Awaitable

from app.plugins.base import DirectLink, RateLimited
```

Cambiar la firma de `_run_one_item`:

```python
async def _run_one_item(
    db: AsyncSession,
    db_lock: asyncio.Lock,
    item: DownloadItem,
    chunks_per_file: int,
    resolver: Callable[[str, str], Awaitable[DirectLink]],
) -> None:
```

Reemplazar la línea `resolved_url = identity(item.url)` por:

```python
        # Resolver acá y no al agregar: las URLs directas caducan, así que la
        # que sirve es la que se pide justo antes de bajar.
        direct = await resolver(item.url, item.hoster)
        resolved_url = direct.url
```

En la llamada a `run_download_item`, agregar después de `rate_limiter=limiter,`:

```python
                headers=direct.headers,
```

Agregar una rama de excepción **antes** del `except Exception` existente:

```python
    except RateLimited as exc:
        async with db_lock:
            await db.rollback()
            # Vuelve a queued, no a error: el hoster no falló, pidió esperar.
            # Un estado propio obligaría a moverlo de ida y vuelta con dos
            # transiciones más que pueden fallar.
            item.status = "queued"
            item.retry_after = exc.retry_at
            item.error_message = None
            await db.commit()
```

Cambiar la firma de `run_pending`:

```python
async def run_pending(
    db: AsyncSession,
    max_concurrent: int,
    chunks_per_file: int,
    resolver: Callable[[str, str], Awaitable[DirectLink]],
    _on_start_for_test: Callable[[str], None] | None = None,
) -> None:
```

Cambiar la consulta de items:

```python
    now = dt.datetime.utcnow()
    result = await db.execute(
        select(DownloadItem)
        .where(
            DownloadItem.status == "queued",
            # Un item agendado sigue en "queued": es trabajo pendiente que
            # todavía no toca, no un estado aparte.
            (DownloadItem.retry_after.is_(None)) | (DownloadItem.retry_after <= now),
        )
        .limit(max_concurrent)
    )
```

Y cambiar la línea del `gather`:

```python
    await asyncio.gather(*(_run_one_item(db, db_lock, item, chunks_per_file, resolver) for item in items))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_scheduler_plugins.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Fix the Fase 1 scheduler tests that still pass `identity`**

En `backend/tests/test_scheduler.py`, `backend/tests/test_checkpointing.py` y `backend/tests/test_settings_applied.py`, reemplazar cada `identity=lambda u: u` por:

```python
        resolver=_direct_resolver,
```

y agregar al principio de cada uno de esos archivos:

```python
from app.plugins.base import DirectLink


async def _direct_resolver(url: str, hoster: str) -> DirectLink:
    return DirectLink(url=url)
```

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/engine/scheduler.py backend/tests
git commit -m "feat: resolve download URLs through plugins and reschedule rate-limited items"
```

---

## Task 12: Cablear el loop de crawl y el resolver real en el lifespan

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/api/settings.py`
- Test: `backend/tests/test_lifespan_crawl.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from app import main
from app.models import GlobalSettings
from app.plugins.base import DirectLink


@pytest.mark.asyncio
async def test_the_resolver_uses_the_plugin_named_on_the_item():
    link = await main._resolve("https://pixeldrain.com/u/abc123", "pixeldrain")
    assert link.url == "https://pixeldrain.com/api/file/abc123?download"


@pytest.mark.asyncio
async def test_an_unknown_hoster_falls_back_to_matching_by_url():
    # Un plugin puede desaparecer entre que se encoló el item y que se levantó
    # (renombre, borrado). Fallar el item por eso sería peor que reintentar el
    # matching, que en el peor caso cae en direct.
    link = await main._resolve("http://example.com/a.zip", "un-plugin-que-ya-no-existe")
    assert link.url == "http://example.com/a.zip"


@pytest.mark.asyncio
async def test_the_crawl_loop_survives_a_failing_tick(monkeypatch):
    ticks = 0

    async def failing_tick():
        nonlocal ticks
        ticks += 1
        raise RuntimeError("db caída")

    monkeypatch.setattr(main, "_crawl_tick", failing_tick)
    monkeypatch.setattr(main, "_CRAWL_POLL_INTERVAL_SECONDS", 0.01)

    task = asyncio.create_task(main._crawl_loop())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ticks >= 2


@pytest.mark.asyncio
async def test_crawl_concurrency_follows_the_settings_row(session):
    session.add(GlobalSettings(id=1, max_concurrent_crawls=9))
    await session.commit()

    assert await main._effective_crawl_limit(session) == 9


@pytest.mark.asyncio
async def test_crawl_concurrency_falls_back_on_a_fresh_install(session):
    assert await main._effective_crawl_limit(session) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_lifespan_crawl.py -q`
Expected: FAIL — `AttributeError: module 'app.main' has no attribute '_resolve'`

- [ ] **Step 3: Wire it in `backend/app/main.py`**

Reemplazar el bloque de `_identity` por:

```python
async def _resolve(url: str, hoster: str) -> DirectLink:
    """Devuelve la URL directa usando el plugin con el que se encoló el item.

    Si ese plugin ya no existe (renombrado o eliminado entre que se encoló y
    que se levantó), se vuelve a matchear por URL en vez de fallar el item:
    en el peor caso cae en `direct`, que es exactamente lo que hacía Fase 1.
    """
    plugin = registry.get(hoster) or registry.find(url)
    return await call_resolve(plugin, url)
```

Agregar los imports necesarios:

```python
from app.crawler.runner import run_pending_crawls
from app.plugins.base import DirectLink
from app.plugins.registry import call_resolve, registry
```

Cambiar `identity=_identity,` por `resolver=_resolve,` en `_scheduler_tick`.

Agregar, después de `_POLL_INTERVAL_SECONDS`:

```python
#: Los crawls son cortos y el usuario está mirando la bandeja, así que se
#: sondea más seguido que las descargas.
_CRAWL_POLL_INTERVAL_SECONDS = 1.0
```

Y después de `_scheduler_loop`:

```python
async def _effective_crawl_limit(db: "AsyncSession") -> int:
    row = await read_settings(db)
    if row is None:
        return _settings.max_concurrent_crawls
    return row.max_concurrent_crawls


async def _crawl_tick() -> None:
    async with SessionLocal() as db:
        await run_pending_crawls(db, max_concurrent=await _effective_crawl_limit(db))


async def _crawl_loop() -> None:
    while True:
        try:
            # Awaited hasta el final antes del siguiente ciclo: run_pending_crawls
            # comparte la misma precondición single-flight que run_pending.
            await _crawl_tick()
        except Exception:  # noqa: BLE001 - un tick malo no puede matar el loop
            logger.exception("crawl tick failed; retrying after the poll interval")
        await asyncio.sleep(_CRAWL_POLL_INTERVAL_SECONDS)
```

En `lifespan`, reemplazar el bloque del task por:

```python
    tasks = []
    if _settings.scheduler_enabled:
        tasks.append(asyncio.create_task(_scheduler_loop()))
        tasks.append(asyncio.create_task(_crawl_loop()))
    try:
        yield
    finally:
        # Parada ordenada por flag, no task.cancel(): el runner de crawl commitea,
        # y una cancelación puede caer dentro del commit y dejar la conexión a
        # medias, que es exactamente lo que envenenó la sesión compartida en
        # Fase 1. El flag solo se observa entre ticks.
        _stop_loops.set()
        for task in tasks:
            await task
```

Y declarar el flag junto a los intervalos, arriba del archivo:

```python
#: Se levanta al apagar. Los loops lo miran entre ticks, nunca a mitad de uno.
_stop_loops = asyncio.Event()
```

Cambiar la condición de ambos loops para que lo respeten. En `_scheduler_loop` y en `_crawl_loop`, reemplazar `while True:` por `while not _stop_loops.is_set():`, y reemplazar la línea final `await asyncio.sleep(<intervalo>)` por:

```python
        with suppress(TimeoutError):
            # wait_for sobre el flag en vez de sleep: apagar no espera un
            # intervalo entero, y despertar temprano es seguro porque el chequeo
            # del while ocurre antes del próximo tick.
            await asyncio.wait_for(_stop_loops.wait(), timeout=<intervalo>)
```

usando `_POLL_INTERVAL_SECONDS` y `_CRAWL_POLL_INTERVAL_SECONDS` respectivamente.

- [ ] **Step 4: Add the env default in `backend/app/config.py`**

Después de `chunks_per_file: int = 4`:

```python
    max_concurrent_crawls: int = 5
```

- [ ] **Step 5: Expose the setting through the API**

En `backend/app/schemas.py`, agregar `max_concurrent_crawls: int` a `SettingsResponse`, y a `UpdateSettingsRequest`:

```python
    max_concurrent_crawls: int = Field(ge=1, le=20)
```

En `backend/app/api/settings.py`, dentro de `update_settings`, agregar después de `row.max_speed_kbps = payload.max_speed_kbps`:

```python
    row.max_concurrent_crawls = payload.max_concurrent_crawls
```

- [ ] **Step 6: Update the settings API test**

En `backend/tests/test_api_settings.py`, agregar `"max_concurrent_crawls": 5` a cada payload de `PUT /settings` y a cada aserción del cuerpo de respuesta.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: run the crawl loop from the lifespan and resolve through the registry"
```

---

## Task 13: Cliente de API del grabber (frontend)

**Files:**
- Modify: `frontend/src/types.ts`
- Create: `frontend/src/api/crawl.ts`
- Test: `frontend/src/api/crawl.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, expect, test, vi } from 'vitest'
import { createCrawlJob, getCrawlJob, promoteResults } from './crawl'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function stubFetch(body: unknown) {
  const mock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body })
  vi.stubGlobal('fetch', mock)
  return mock
}

test('createCrawlJob posts the raw pasted text', async () => {
  const mock = stubFetch({ id: 'j1', raw_input: 'http://x/a', status: 'pending', results: [] })

  await createCrawlJob('http://x/a')

  expect(mock).toHaveBeenCalledWith(
    '/crawl-jobs',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ links: 'http://x/a' }) }),
  )
})

test('getCrawlJob fetches a single job by id', async () => {
  const mock = stubFetch({ id: 'j1', raw_input: '', status: 'done', results: [] })

  await getCrawlJob('j1')

  expect(mock).toHaveBeenCalledWith('/crawl-jobs/j1', expect.anything())
})

test('promoteResults sends the package name and the chosen ids', async () => {
  const mock = stubFetch({ id: 'p1', name: 'Mi paquete', status: 'queued', target_dir: '/x', items: [] })

  await promoteResults('j1', 'Mi paquete', ['r1', 'r2'])

  expect(mock).toHaveBeenCalledWith(
    '/crawl-jobs/j1/promote',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ name: 'Mi paquete', result_ids: ['r1', 'r2'] }),
    }),
  )
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- crawl.test.ts`
Expected: FAIL — `Failed to resolve import "./crawl"`

- [ ] **Step 3: Add the types to `frontend/src/types.ts`**

En `DownloadItem`, después de `error_message: string | null`:

```typescript
  /** Qué plugin lo resolvió; 'direct' para un enlace directo. */
  hoster: string
  /** ISO 8601 mientras el hoster pide esperar; null en el caso normal. */
  retry_after: string | null
```

Al final del archivo:

```typescript
export type CrawlJobStatus = 'pending' | 'running' | 'done' | 'error'
export type CrawlResultStatus = 'ok' | 'dead' | 'error'

export interface CrawlResult {
  id: string
  url: string
  filename: string
  size: number | null
  hoster: string
  status: CrawlResultStatus
  error_message: string | null
}

export interface CrawlJob {
  id: string
  raw_input: string
  status: CrawlJobStatus
  error_message: string | null
  results: CrawlResult[]
}
```

- [ ] **Step 4: Implement `frontend/src/api/crawl.ts`**

```typescript
import { apiFetch } from './client'
import type { CrawlJob, Package } from '../types'

export function createCrawlJob(links: string): Promise<CrawlJob> {
  return apiFetch('/crawl-jobs', { method: 'POST', body: JSON.stringify({ links }) })
}

export function getCrawlJob(id: string): Promise<CrawlJob> {
  return apiFetch(`/crawl-jobs/${id}`)
}

/** Convierte los resultados elegidos en un paquete descargable. */
export function promoteResults(jobId: string, name: string, resultIds: string[]): Promise<Package> {
  return apiFetch(`/crawl-jobs/${jobId}/promote`, {
    method: 'POST',
    body: JSON.stringify({ name, result_ids: resultIds }),
  })
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm run test -- crawl.test.ts`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/crawl.ts frontend/src/api/crawl.test.ts frontend/src/types.ts
git commit -m "feat: add the crawl job API client"
```

---

## Task 14: Pantalla del LinkGrabber

**Files:**
- Create: `frontend/src/pages/LinkGrabber.tsx`
- Create: `frontend/src/pages/LinkGrabber.css`
- Test: `frontend/src/pages/LinkGrabber.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import LinkGrabber from './LinkGrabber'
import * as crawlApi from '../api/crawl'
import type { CrawlJob } from '../types'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const doneJob: CrawlJob = {
  id: 'j1',
  raw_input: 'http://x/dir/',
  status: 'done',
  error_message: null,
  results: [
    { id: 'r1', url: 'http://x/a.zip', filename: 'a.zip', size: 1024, hoster: 'direct', status: 'ok', error_message: null },
    { id: 'r2', url: 'http://x/b.zip', filename: 'b.zip', size: null, hoster: 'direct', status: 'dead', error_message: 'no existe' },
  ],
}

test('renders the discovered files once the job is done', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)

  expect(await screen.findByText('a.zip')).toBeInTheDocument()
  expect(screen.getByText('b.zip')).toBeInTheDocument()
  expect(screen.getByText('1.0 KB')).toBeInTheDocument()
})

test('dead links are shown but not selected', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)
  await screen.findByText('a.zip')

  // Verlos importa: dicen qué se perdió de la lista pegada. Tildarlos solo
  // encolaría un fallo garantizado.
  expect(screen.getByLabelText('a.zip')).toBeChecked()
  expect(screen.getByLabelText('b.zip')).not.toBeChecked()
  expect(screen.getByLabelText('b.zip')).toBeDisabled()
})

test('promotes only the checked results', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)
  const promote = vi.spyOn(crawlApi, 'promoteResults').mockResolvedValue({
    id: 'p1', name: 'Mi paquete', status: 'queued', target_dir: '/x', items: [],
  })
  const onDone = vi.fn()

  render(<LinkGrabber jobId="j1" onDone={onDone} onBack={vi.fn()} />)
  await screen.findByText('a.zip')

  fireEvent.change(screen.getByLabelText('Nombre del paquete'), { target: { value: 'Mi paquete' } })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar a la cola' }))

  await waitFor(() => expect(promote).toHaveBeenCalledWith('j1', 'Mi paquete', ['r1']))
  await waitFor(() => expect(onDone).toHaveBeenCalled())
})

test('keeps polling while the job is still running', async () => {
  vi.useFakeTimers()
  const get = vi
    .spyOn(crawlApi, 'getCrawlJob')
    .mockResolvedValueOnce({ ...doneJob, status: 'running', results: [] })
    .mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)

  await vi.waitFor(() => expect(screen.getByText(/Buscando/)).toBeInTheDocument())
  await vi.advanceTimersByTimeAsync(2000)

  await vi.waitFor(() => expect(screen.getByText('a.zip')).toBeInTheDocument())
  expect(get.mock.calls.length).toBeGreaterThan(1)
})

test('stops polling once the job is done', async () => {
  vi.useFakeTimers()
  const get = vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)
  await vi.waitFor(() => expect(screen.getByText('a.zip')).toBeInTheDocument())

  const callsWhenDone = get.mock.calls.length
  await vi.advanceTimersByTimeAsync(10000)

  // Un job terminado no cambia más; seguir sondeándolo es tráfico puro.
  expect(get.mock.calls.length).toBe(callsWhenDone)
})

test('submit is disabled when nothing is selected', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue({
    ...doneJob,
    results: [doneJob.results[1]], // solo el muerto
  })

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)
  await screen.findByText('b.zip')

  expect(screen.getByRole('button', { name: 'Agregar a la cola' })).toBeDisabled()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- LinkGrabber`
Expected: FAIL — `Failed to resolve import "./LinkGrabber"`

- [ ] **Step 3: Implement `frontend/src/pages/LinkGrabber.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react'
import { getCrawlJob, promoteResults } from '../api/crawl'
import { UnauthorizedError } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { formatBytes } from '../format'
import type { CrawlJob } from '../types'
import './LinkGrabber.css'

interface Props {
  jobId: string
  onDone: () => void
  onBack: () => void
  onUnauthorized?: () => void
}

const POLL_INTERVAL_MS = 1000

export default function LinkGrabber({ jobId, onDone, onBack, onUnauthorized }: Props) {
  const [job, setJob] = useState<CrawlJob | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const finished = job?.status === 'done' || job?.status === 'error'

  const refresh = useCallback(async () => {
    try {
      const fetched = await getCrawlJob(jobId)
      setJob(fetched)
      // Los muertos quedan visibles pero fuera de la selección: tildarlos solo
      // encola un fallo garantizado.
      setSelected((prev) =>
        prev.size > 0 ? prev : new Set(fetched.results.filter((r) => r.status === 'ok').map((r) => r.id)),
      )
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        onUnauthorized?.()
        return
      }
      setError(e instanceof Error ? e.message : 'No se pudo cargar el análisis')
    }
  }, [jobId, onUnauthorized])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    // Un job terminado no cambia más; seguir sondeándolo es tráfico puro.
    if (finished) return
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [finished, refresh])

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await promoteResults(jobId, name.trim() || 'Paquete sin nombre', [...selected])
      onDone()
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.()
        return
      }
      setError(err instanceof Error ? err.message : 'No se pudo crear el paquete')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="grabber" onSubmit={handleSubmit}>
      <div className="grabber__header">
        <button type="button" onClick={onBack}>
          Volver
        </button>
        {job && <StatusBadge status={job.status} />}
      </div>

      <h1 className="grabber__title">Enlaces encontrados</h1>

      {error && (
        <p className="grabber__error" role="alert">
          {error}
        </p>
      )}

      {!finished && <p className="grabber__pending">Buscando qué hay detrás de los enlaces…</p>}

      {job && job.results.length > 0 && (
        <ul className="grabber__list">
          {job.results.map((result) => (
            <li className="grabber__row" key={result.id}>
              <input
                type="checkbox"
                id={`r-${result.id}`}
                aria-label={result.filename}
                checked={selected.has(result.id)}
                disabled={result.status !== 'ok'}
                onChange={() => toggle(result.id)}
              />
              <label className="grabber__name" htmlFor={`r-${result.id}`} title={result.url}>
                {result.filename}
              </label>
              <span className="grabber__size">{formatBytes(result.size)}</span>
              <span className="grabber__hoster">{result.hoster}</span>
              <StatusBadge status={result.status} />
              {result.error_message && <span className="grabber__why">{result.error_message}</span>}
            </li>
          ))}
        </ul>
      )}

      {finished && job?.results.length === 0 && (
        <p className="grabber__pending">No se encontró ningún archivo detrás de esos enlaces.</p>
      )}

      <div className="grabber__footer">
        <div className="grabber__field">
          <label htmlFor="pkg-name">Nombre del paquete</label>
          <input
            id="pkg-name"
            placeholder="Paquete sin nombre"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <button type="submit" className="grabber__primary" disabled={selected.size === 0 || submitting}>
          Agregar a la cola
        </button>
      </div>
    </form>
  )
}
```

- [ ] **Step 4: Create `frontend/src/pages/LinkGrabber.css`**

```css
.grabber {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.grabber__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.grabber__title {
  margin: 0;
  font-size: 1.25rem;
}

.grabber__pending {
  margin: 0;
  padding: 1.5rem 1rem;
  text-align: center;
  color: var(--text-muted);
  border: 1px dashed var(--border);
  border-radius: 8px;
}

.grabber__list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.grabber__row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
}

.grabber__name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.grabber__size,
.grabber__hoster {
  font-size: 0.8rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.grabber__why {
  font-size: 0.8rem;
  color: var(--danger);
}

.grabber__footer {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
}

.grabber__field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex: 1;
}

.grabber__field label {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.grabber__error {
  margin: 0;
  font-size: 0.9rem;
  color: var(--danger);
}

.grabber__primary {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-text);
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm run test -- LinkGrabber`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LinkGrabber.tsx frontend/src/pages/LinkGrabber.css frontend/src/pages/LinkGrabber.test.tsx
git commit -m "feat: add the LinkGrabber tray for reviewing discovered files"
```

---

## Task 15: El modal de enlaces crea un crawl job

**Files:**
- Modify: `frontend/src/components/AddLinksModal.tsx`
- Modify: `frontend/src/components/AddLinksModal.test.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/pages/Dashboard.test.tsx`

- [ ] **Step 1: Write the failing Dashboard test**

Agregar a `frontend/src/pages/Dashboard.test.tsx`, y agregar el import `import * as crawlApi from '../api/crawl'` al principio:

```tsx
test('pasting links creates a crawl job and opens the tray', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  const create = vi.spyOn(crawlApi, 'createCrawlJob').mockResolvedValue({
    id: 'j1', raw_input: 'http://x/a.zip', status: 'pending', error_message: null, results: [],
  })
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue({
    id: 'j1', raw_input: 'http://x/a.zip', status: 'done', error_message: null,
    results: [{ id: 'r1', url: 'http://x/a.zip', filename: 'a.zip', size: 10, hoster: 'direct', status: 'ok', error_message: null }],
  })
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Agregar enlaces' }))
  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: 'http://x/a.zip' } })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  // El modal ya no crea un paquete: ahora abre el análisis y el usuario
  // confirma qué baja.
  await waitFor(() => expect(create).toHaveBeenCalledWith('http://x/a.zip'))
  expect(await screen.findByText('a.zip')).toBeInTheDocument()
})
```

- [ ] **Step 2: Update the modal's own test**

En `frontend/src/components/AddLinksModal.test.tsx`, reemplazar cada `{ name: 'Agregar' }` por `{ name: 'Analizar' }`, y eliminar el test `falls back to a default package name` junto con la aserción `expect.any(String)` del test de duplicados, dejándolo así:

```tsx
test('drops duplicate URLs before submitting', () => {
  const onSubmit = vi.fn()
  render(<AddLinksModal onSubmit={onSubmit} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), {
    target: { value: 'https://x/a.zip\nhttps://x/a.zip\nhttps://x/b.zip' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip', 'https://x/b.zip'])
  expect(screen.getByText(/1 enlace duplicado/)).toBeInTheDocument()
})
```

Y en `parses newline-separated URLs and calls onSubmit`, quitar el `fireEvent.change` del nombre del paquete y esperar:

```tsx
  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip', 'https://x/b.zip', 'https://x/c.zip'])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm run test -- AddLinksModal Dashboard`
Expected: FAIL — el botón sigue diciendo "Agregar" y `onSubmit` sigue recibiendo dos argumentos

- [ ] **Step 4: Simplify `frontend/src/components/AddLinksModal.tsx`**

Cambiar la interfaz `Props`:

```tsx
interface Props {
  onSubmit: (urls: string[]) => void
  onClose: () => void
  /** Set while the crawl job is being created. */
  submitting?: boolean
  error?: string | null
}
```

Cambiar `handleSubmit`:

```tsx
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    // El nombre del paquete ya no se pide acá: se elige al confirmar, cuando
    // el usuario ya vio qué archivos aparecieron.
    onSubmit(urls)
  }
```

Eliminar el bloque `<div className="modal__field">` del nombre del paquete y el `useState` de `name`, y cambiar el texto del botón de envío a `Analizar`.

- [ ] **Step 5: Wire it in `frontend/src/pages/Dashboard.tsx`**

Agregar el import:

```tsx
import { createCrawlJob } from '../api/crawl'
import LinkGrabber from './LinkGrabber'
```

Cambiar el tipo `View`:

```tsx
type View =
  | { name: 'list' }
  | { name: 'detail'; packageId: string }
  | { name: 'settings' }
  | { name: 'grabber'; jobId: string }
```

Reemplazar `handleCreate` por:

```tsx
  async function handleAnalyze(urls: string[]) {
    setCreating(true)
    setCreateError(null)
    try {
      const job = await createCrawlJob(urls.join('\n'))
      setShowModal(false)
      setView({ name: 'grabber', jobId: job.id })
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        onUnauthorized?.()
        return
      }
      // El modal queda abierto: cerrarlo tiraría los enlaces recién pegados.
      setCreateError(e instanceof Error ? e.message : 'No se pudo analizar los enlaces')
    } finally {
      setCreating(false)
    }
  }
```

Agregar la vista antes del `if (view.name === 'detail')`:

```tsx
  if (view.name === 'grabber') {
    return (
      <LinkGrabber
        jobId={view.jobId}
        onBack={() => setView({ name: 'list' })}
        onDone={() => {
          setView({ name: 'list' })
          void refresh()
        }}
        onUnauthorized={onUnauthorized}
      />
    )
  }
```

Y cambiar el uso del modal:

```tsx
        <AddLinksModal
          onSubmit={(urls) => void handleAnalyze(urls)}
          onClose={() => {
            setShowModal(false)
            setCreateError(null)
          }}
          submitting={creating}
          error={createError}
        />
```

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npm run test && npx tsc -b`
Expected: All PASS, `tsc` limpio

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat: route pasted links through the crawl tray instead of creating a package directly"
```

---

## Task 16: El dashboard muestra las esperas

**Files:**
- Modify: `frontend/src/components/PackageRow.tsx`
- Modify: `frontend/src/components/PackageRow.test.tsx`

- [ ] **Step 1: Write the failing test**

Agregar a `frontend/src/components/PackageRow.test.tsx`:

```tsx
test('shows when a waiting item resumes instead of calling it an error', () => {
  const waiting: Package = {
    ...pkg,
    status: 'queued',
    items: [
      {
        ...pkg.items[0],
        status: 'queued',
        retry_after: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
      },
    ],
  }

  render(<PackageRow package={waiting} onPause={noop} onResume={noop} onCancel={noop} />)

  // "Esto está agendado" y "esto se rompió" se confunden fácil, y la confusión
  // hace que la gente cancele descargas que iban bien.
  expect(screen.getByText(/esperando hasta/i)).toBeInTheDocument()
})

test('does not claim a wait when there is none', () => {
  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} />)
  expect(screen.queryByText(/esperando hasta/i)).not.toBeInTheDocument()
})
```

Y agregar `hoster: 'direct', retry_after: null,` a cada item del `const pkg` que ya existe en ese archivo.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- PackageRow`
Expected: FAIL — no existe el texto "esperando hasta"

- [ ] **Step 3: Implement it in `frontend/src/components/PackageRow.tsx`**

Agregar antes del `return`:

```tsx
  // El primero que vuelve es el que define cuándo el paquete se mueve otra vez.
  const waitingUntil = pkg.items
    .map((i) => i.retry_after)
    .filter((value): value is string => value !== null)
    .sort()[0]
```

Y dentro del `<div className="package-row__actions">`, antes de los botones:

```tsx
        {waitingUntil && (
          <span className="package-row__waiting">
            esperando hasta {new Date(waitingUntil).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
```

Agregar a `frontend/src/components/PackageRow.css`:

```css
.package-row__waiting {
  align-self: center;
  margin-right: auto;
  font-size: 0.8rem;
  color: var(--text-muted);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- PackageRow`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PackageRow.tsx frontend/src/components/PackageRow.css frontend/src/components/PackageRow.test.tsx
git commit -m "feat: show scheduled waits as waits, not as failures"
```

---

## Task 17: Control de concurrencia de crawl en Settings

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/pages/Settings.test.tsx`

- [ ] **Step 1: Write the failing test**

En `frontend/src/pages/Settings.test.tsx`, agregar `max_concurrent_crawls: 5,` al objeto `saved`, y agregar:

```tsx
test('saves the crawl concurrency limit', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue(saved)
  const updateSpy = vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue(saved)

  render(<Settings onClose={() => {}} />)
  await waitFor(() => expect(screen.getByLabelText('Análisis simultáneos')).toHaveValue(5))

  fireEvent.change(screen.getByLabelText('Análisis simultáneos'), { target: { value: '8' } })
  fireEvent.click(screen.getByRole('button', { name: 'Guardar' }))

  await waitFor(() =>
    expect(updateSpy).toHaveBeenCalledWith({ ...saved, max_concurrent_crawls: 8 }),
  )
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- Settings`
Expected: FAIL — no existe el campo "Análisis simultáneos"

- [ ] **Step 3: Add the field**

En `frontend/src/types.ts`, agregar a `AppSettings`:

```typescript
  max_concurrent_crawls: number
```

En `frontend/src/pages/Settings.tsx`:

- agregar `'max_concurrent_crawls'` al tipo `NumericKey`
- agregar a `BOUNDS`: `max_concurrent_crawls: { min: 1, max: 20 },`
- agregar `max_concurrent_crawls: ''` al estado inicial de `numeric`
- agregar `max_concurrent_crawls: String(loaded.max_concurrent_crawls),` dentro del `setNumeric` del `useEffect`
- agregar el campo después del de descargas simultáneas:

```tsx
      <NumberField
        id="max-crawls"
        label="Análisis simultáneos"
        field="max_concurrent_crawls"
        value={numeric.max_concurrent_crawls}
        onChange={setNumeric}
      />
```

- [ ] **Step 4: Run the full frontend suite**

Run: `cd frontend && npm run test && npx tsc -b`
Expected: All PASS, `tsc` limpio

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: expose the crawl concurrency limit in Settings"
```

---

## Task 18: Re-captura de fixtures y tests contra sitios reales

**Files:**
- Create: `backend/tests/live/__init__.py`
- Create: `backend/tests/live/test_live_hosters.py`
- Create: `backend/tests/fixtures/pages/README.md`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Register the marker in `backend/pyproject.toml`**

Reemplazar la sección `[tool.pytest.ini_options]` por:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
# Los tests live salen a internet: quedan fuera de la corrida normal para que
# la suite no dependa de que un hoster de terceros esté arriba.
addopts = "-m 'not live'"
markers = [
    "live: golpea el sitio real del hoster; correr a mano con -m live",
]
```

- [ ] **Step 2: Write the live tests**

Create `backend/tests/live/__init__.py` as an empty file.

Create `backend/tests/live/test_live_hosters.py`:

```python
"""Tests contra los sitios reales. Excluidos de la corrida normal.

Un fixture guardado es una foto: prueba que el parser entiende la página que
capturamos, no la que el sitio sirve hoy. Ningún test offline puede detectar
que el hoster cambió el HTML anoche — para eso están estos.

Correr a mano: pytest -m live tests/live -v
"""

import pytest

from app.plugins.base import CrawlResult
from app.plugins.pixeldrain import PixeldrainHoster

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_pixeldrain_api_still_answers_the_shape_we_parse():
    # Archivo público de larga data usado como canario. Si este test falla,
    # o cambió la API o el archivo se borró: revisar antes de tocar el plugin.
    plugin = PixeldrainHoster()

    result = await plugin.crawl("https://pixeldrain.com/u/6JGMFJTF")

    assert isinstance(result, CrawlResult)
    assert len(result.files) == 1
    assert result.files[0].filename
    assert result.files[0].size and result.files[0].size > 0
```

- [ ] **Step 3: Write the fixture-refresh instructions**

Create `backend/tests/fixtures/pages/README.md`:

```markdown
# Páginas guardadas

Cada archivo de esta carpeta es una captura real de un hoster, usada por los
tests de plugins para correr sin red.

**Son fotos.** Prueban que el parser entiende la página que capturamos, no la
que el sitio sirve hoy. Un plugin puede estar roto en producción con todos sus
tests en verde. Contra eso están los tests de `backend/tests/live/`.

## Re-capturar una página

```bash
curl -sL "https://ejemplo.com/carpeta/" -o backend/tests/fixtures/pages/<nombre>.html
```

Después de re-capturar, correr los tests del plugin correspondiente. Si fallan,
el sitio cambió y hay que actualizar el parser — que es exactamente lo que la
captura sirve para detectar.

Quitar de la página guardada cualquier token de sesión o dato personal antes de
commitearla.

## Correr los tests contra los sitios reales

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -m live tests/live -v
```

Salen a internet y pueden fallar por causas ajenas al código (el hoster caído,
el archivo canario borrado). Por eso están fuera de la corrida normal.
```

- [ ] **Step 4: Verify the normal run excludes them**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: All PASS, y `tests/live` no aparece entre los recolectados

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -m live tests/live -q`
Expected: PASS (requiere internet)

- [ ] **Step 5: Commit**

```bash
git add backend/tests/live backend/tests/fixtures/pages/README.md backend/pyproject.toml
git commit -m "test: add opt-in live hoster tests and document fixture refreshing"
```

---

## Task 19: Verificación end-to-end del stack completo

**Files:** ninguno (solo verificación)

- [ ] **Step 1: Full suites and build**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
cd ../frontend && npm run test && npx tsc -b && npm run build
```
Expected: todo PASS

- [ ] **Step 2: Start the stack**

```bash
cd "$(git rev-parse --show-toplevel)"
cp .env.example .env
docker compose up --build -d
docker compose logs backend | tail -20
```
Expected: `Running upgrade 0001 -> 0002`, luego `Uvicorn running on http://0.0.0.0:8000`

- [ ] **Step 3: Serve a folder to crawl**

El entorno puede no tener DNS saliente desde los contenedores (ocurrió en la verificación de Fase 1). Se levanta un autoindex dentro de la red de compose:

```bash
NET=$(docker network ls --format '{{.Name}}' | grep -m1 default)
docker run -d --name cascade-fs --network "$NET" nginx:1.27-alpine
docker exec cascade-fs sh -c 'mkdir -p /usr/share/nginx/html/media && \
  head -c 3000000 /dev/urandom > /usr/share/nginx/html/media/a.bin && \
  head -c 2000000 /dev/urandom > /usr/share/nginx/html/media/b.bin && \
  printf "server{listen 80;location / {root /usr/share/nginx/html;autoindex on;}}" \
    > /etc/nginx/conf.d/default.conf && nginx -s reload'
```

- [ ] **Step 4: Crawl the folder through the API**

```bash
CK=/tmp/ck.txt
curl -s -c $CK -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" -d '{"username":"admin","password":"changeme"}'
JOB=$(curl -s -b $CK -X POST http://localhost:8080/crawl-jobs \
  -H "Content-Type: application/json" -d '{"links":"http://cascade-fs/media/"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
sleep 5
curl -s -b $CK http://localhost:8080/crawl-jobs/$JOB | python -m json.tool
```
Expected: `status: "done"` y dos resultados (`a.bin`, `b.bin`) con su `size` y `hoster: "open_directory"`

- [ ] **Step 5: Promote and verify the download lands on disk**

```bash
IDS=$(curl -s -b $CK http://localhost:8080/crawl-jobs/$JOB \
  | python -c "import sys,json;print(json.dumps([r['id'] for r in json.load(sys.stdin)['results']]))")
PKG=$(curl -s -b $CK -X POST http://localhost:8080/crawl-jobs/$JOB/promote \
  -H "Content-Type: application/json" -d "{\"name\":\"E2E\",\"result_ids\":$IDS}" \
  | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
sleep 15
docker compose exec -T backend ls -la /downloads/$PKG
```
Expected: `a.bin` y `b.bin` con sus tamaños completos

- [ ] **Step 6: Check it in the browser**

Abrir `http://localhost:8080`, entrar, pegar `http://cascade-fs/media/` en "Agregar enlaces", pulsar "Analizar".
Expected: la bandeja lista los dos archivos con tamaño y hoster; al confirmar aparecen en el dashboard y avanzan.

- [ ] **Step 7: Tear down**

```bash
docker rm -f cascade-fs
docker compose down -v
rm .env
```

- [ ] **Step 8: Record the result**

Si algún paso falla, anotarlo como tarea de seguimiento al final de este plan antes de dar Fase 2 por cerrada — no parchear en silencio sin actualizar plan o spec.

---

## Fuera de alcance (confirmado)

- Cuentas premium → Fase 2b.
- Hosters con criptografía propia (Mega) y sitios que exigen ejecutar JavaScript → más adelante; el contrato `async` de `resolve` los admite sin rediseño.
- CAPTCHA → Fase 3.
- Extracción de archivos y contenedores → Fase 4.
