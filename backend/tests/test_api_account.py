"""La cuenta es opcional y solo sirve para recuperar el token de dueño."""

import pytest

from tests.conftest import TEST_OWNER

CREDS = {"username": "daniel", "password": "una-clave-larga"}


@pytest.mark.asyncio
async def test_a_fresh_browser_has_no_account(async_auth_client):
    body = (await async_auth_client.get("/account")).json()
    assert body["username"] is None


@pytest.mark.asyncio
async def test_registering_binds_this_browser_without_moving_its_downloads(async_auth_client):
    await async_auth_client.post("/crawl-jobs", json={"links": "http://x/a"})

    response = await async_auth_client.post("/account/register", json=CREDS)

    assert response.status_code == 201
    assert response.json()["username"] == "daniel"
    # Lo ya descargado sigue ahí sin mover un registro: owner_id no cambia al
    # registrarse, la cuenta solo lo vuelve recuperable.
    assert len((await async_auth_client.get("/crawl-jobs")).json()) == 1


@pytest.mark.asyncio
async def test_logging_in_returns_the_token_that_unlocks_that_history(async_auth_client):
    await async_auth_client.post("/crawl-jobs", json={"links": "http://x/a"})
    await async_auth_client.post("/account/register", json=CREDS)

    token = (await async_auth_client.post("/account/login", json=CREDS)).json()["owner_token"]

    # Es exactamente el flujo del segundo dispositivo: se pide el token con
    # usuario y contraseña, se guarda, y desde ahí se ve la misma lista.
    assert token == TEST_OWNER

    async_auth_client.headers["X-Cascade-Owner"] = "dispositivonuevo00000000000000ab"
    assert (await async_auth_client.get("/crawl-jobs")).json() == []

    async_auth_client.headers["X-Cascade-Owner"] = token
    assert len((await async_auth_client.get("/crawl-jobs")).json()) == 1


@pytest.mark.asyncio
async def test_login_does_not_need_an_owner_header(async_client):
    async_client.headers["X-Cascade-Owner"] = TEST_OWNER
    await async_client.post("/account/register", json=CREDS)

    # Es el caso del dispositivo nuevo, que todavía no tiene el token correcto.
    async_client.headers.pop("X-Cascade-Owner", None)
    response = await async_client.post("/account/login", json=CREDS)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_wrong_password_and_an_unknown_user_look_the_same(async_auth_client):
    await async_auth_client.post("/account/register", json=CREDS)

    wrong = await async_auth_client.post("/account/login", json={**CREDS, "password": "otra-clave-x"})
    unknown = await async_auth_client.post("/account/login", json={"username": "nadie", "password": "una-clave-larga"})

    # Distinguirlos confirmaría qué nombres de usuario existen.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


@pytest.mark.asyncio
async def test_a_username_cannot_be_taken_twice(async_auth_client):
    await async_auth_client.post("/account/register", json=CREDS)

    async_auth_client.headers["X-Cascade-Owner"] = "otronavegador00000000000000000ab"
    response = await async_auth_client.post("/account/register", json=CREDS)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_a_browser_cannot_register_twice(async_auth_client):
    await async_auth_client.post("/account/register", json=CREDS)

    response = await async_auth_client.post("/account/register", json={**CREDS, "username": "otro"})

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_the_password_is_never_stored_in_the_clear(async_auth_client, session):
    from sqlalchemy import select

    from app.models import User

    await async_auth_client.post("/account/register", json=CREDS)

    user = (await session.execute(select(User))).scalar_one()
    assert CREDS["password"] not in user.password_hash


@pytest.mark.asyncio
async def test_a_short_password_is_refused(async_auth_client):
    response = await async_auth_client.post("/account/register", json={"username": "daniel", "password": "corta"})
    assert response.status_code == 422
