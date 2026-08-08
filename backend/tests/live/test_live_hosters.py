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
