"""The settings row must actually drive behavior, not just round-trip via the API."""

import pytest

from app.main import _effective_limits
from app.api.packages import _target_dir_root
from app.models import GlobalSettings


@pytest.mark.asyncio
async def test_scheduler_limits_fall_back_to_env_on_a_fresh_install(session):
    # No settings row exists until the first GET/PUT /settings.
    assert await _effective_limits(session) == (3, 4)


@pytest.mark.asyncio
async def test_scheduler_limits_follow_the_settings_row(session):
    session.add(GlobalSettings(id=1, max_concurrent_downloads=7, chunks_per_file=2))
    await session.commit()

    # Changing these in the UI has to take effect on the next tick - requiring
    # a container restart for a settings change would make the page misleading.
    assert await _effective_limits(session) == (7, 2)


@pytest.mark.asyncio
async def test_the_speed_cap_follows_the_settings_row(session):
    from app.engine.rate_limiter import limiter

    session.add(GlobalSettings(id=1, max_speed_kbps=500))
    await session.commit()

    await _effective_limits(session)

    # Stored in KB/s, enforced in bytes/s.
    assert limiter.rate_bytes_per_second == 500 * 1024

    row = await session.get(GlobalSettings, 1)
    row.max_speed_kbps = 0
    await session.commit()
    await _effective_limits(session)

    # 0 means "sin límite", not "stall every download".
    assert limiter.rate_bytes_per_second == 0


def test_the_download_root_comes_from_the_environment_only():
    """Dejó de ser un ajuste de usuario.

    El archivo se entrega al navegador, que lo guarda donde guarda todo; dónde
    lo deja el servidor mientras tanto es infraestructura. Antes esto se leía
    de la fila de settings y se ofrecía en la UI.
    """
    from app.api.packages import _target_dir_root

    assert _target_dir_root() == "/downloads"


