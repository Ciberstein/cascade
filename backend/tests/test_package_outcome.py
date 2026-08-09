"""El estado del paquete es lo único que se ve en el dashboard.

Si un paquete cuyos items fallaron se queda en "queued", el usuario ve 0% y
ninguna señal de error, y tiene que abrir el detalle para descubrir que no
está descargando nada. Fue exactamente lo que pasó en la primera prueba real.
"""

import pytest
from sqlalchemy import select

from app.engine.scheduler import run_pending
from app.models import DownloadItem, Package
from app.plugins.base import DirectLink, PluginError


async def _boom_resolver(url: str, hoster: str) -> DirectLink:
    raise PluginError("el sitio no devolvió un archivo")


async def _direct_resolver(url: str, hoster: str) -> DirectLink:
    return DirectLink(url=url)


async def _package_with(session, tmp_path, urls):
    package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    for n, url in enumerate(urls):
        session.add(
            DownloadItem(
                package_id=package.id, url=url, filename=f"f{n}.bin",
                status="queued", hoster="direct",
            )
        )
    await session.commit()
    return package


@pytest.mark.asyncio
async def test_a_package_whose_items_all_failed_ends_in_error(session, tmp_path):
    package = await _package_with(session, tmp_path, ["http://x/a"])

    await run_pending(session, max_concurrent=2, chunks_per_file=1, resolver=_boom_resolver)

    await session.refresh(package)
    assert package.status == "error"


@pytest.mark.asyncio
async def test_a_partially_failed_package_still_ends_in_error(session, test_server, tmp_path):
    _, good = await test_server(b"Z" * 100)
    package = await _package_with(session, tmp_path, [good, "http://x/bad"])

    async def mixed(url, hoster):
        if url == good:
            return DirectLink(url=url)
        raise PluginError("no se pudo resolver")

    await run_pending(session, max_concurrent=2, chunks_per_file=1, resolver=mixed)

    await session.refresh(package)
    # No "completed": decir que terminó bien cuando falta un archivo es peor
    # que decir que algo salió mal.
    assert package.status == "error"


@pytest.mark.asyncio
async def test_a_fully_downloaded_package_still_completes(session, test_server, tmp_path):
    _, url = await test_server(b"Z" * 100)
    package = await _package_with(session, tmp_path, [url])

    await run_pending(session, max_concurrent=2, chunks_per_file=1, resolver=_direct_resolver)

    await session.refresh(package)
    assert package.status == "completed"


@pytest.mark.asyncio
async def test_a_package_with_work_left_is_not_judged_yet(session, test_server, tmp_path):
    _, url = await test_server(b"Z" * 100)
    package = await _package_with(session, tmp_path, [url])
    # Un segundo item que este pase no levanta (el limite es 1).
    session.add(
        DownloadItem(package_id=package.id, url="http://x/later", filename="later.bin",
                     status="queued", hoster="direct")
    )
    await session.commit()

    await run_pending(session, max_concurrent=1, chunks_per_file=1, resolver=_direct_resolver)

    await session.refresh(package)
    assert package.status == "queued"


@pytest.mark.asyncio
async def test_startup_reconciles_a_package_left_disagreeing_with_its_items(session, tmp_path):
    """Exactamente lo que se vio probando: un paquete en "queued" cuyo único
    item ya había fallado, mostrando 0% en el dashboard para siempre.

    El veredicto normal solo corre sobre paquetes con items en el lote del
    tick, y ese item nunca vuelve a entrar en uno. Sin esta reconciliación no
    hay nada que lo corrija.
    """
    from app.engine.scheduler import reconcile_package_statuses

    package = Package(name="viejo", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    session.add(
        DownloadItem(package_id=package.id, url="http://x/a", filename="a.bin",
                     status="error", hoster="direct", error_message="algo falló")
    )
    await session.commit()

    await reconcile_package_statuses(session)

    await session.refresh(package)
    assert package.status == "error"


@pytest.mark.asyncio
async def test_reconciliation_leaves_a_package_still_working_alone(session, tmp_path):
    from app.engine.scheduler import reconcile_package_statuses

    package = Package(name="en curso", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    session.add_all([
        DownloadItem(package_id=package.id, url="http://x/a", filename="a.bin",
                     status="completed", hoster="direct"),
        DownloadItem(package_id=package.id, url="http://x/b", filename="b.bin",
                     status="queued", hoster="direct"),
    ])
    await session.commit()

    await reconcile_package_statuses(session)

    await session.refresh(package)
    assert package.status == "queued"


@pytest.mark.asyncio
async def test_reconciliation_does_not_override_a_user_decision(session, tmp_path):
    from app.engine.scheduler import reconcile_package_statuses

    package = Package(name="cancelado", status="canceled", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    session.add(
        DownloadItem(package_id=package.id, url="http://x/a", filename="a.bin",
                     status="error", hoster="direct")
    )
    await session.commit()

    await reconcile_package_statuses(session)

    await session.refresh(package)
    # Pausar o cancelar es del usuario: reescribirlo a "error" al reiniciar
    # borraría su decisión.
    assert package.status == "canceled"
