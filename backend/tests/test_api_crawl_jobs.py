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
async def test_a_request_without_an_owner_token_is_rejected(async_client):
    # Ya no hay login, pero la cabecera de dueño no es opcional: sin ella el
    # servidor no sabe de quién es nada.
    async_client.headers.pop("X-Cascade-Owner", None)

    assert (await async_client.post("/crawl-jobs", json={"links": "http://x/a"})).status_code == 400
    assert (await async_client.get("/crawl-jobs")).status_code == 400


@pytest.mark.asyncio
async def test_a_guessable_owner_token_is_rejected(async_client):
    # El token es la única credencial: uno corto se adivina, y adivinarlo es
    # leer el historial ajeno.
    async_client.headers["X-Cascade-Owner"] = "abc"

    assert (await async_client.get("/crawl-jobs")).status_code == 400


@pytest.mark.asyncio
async def test_one_browser_never_sees_another_browsers_jobs(async_auth_client):
    await async_auth_client.post("/crawl-jobs", json={"links": "http://x/mio"})

    # Se cambia en el cliente y no por request: httpx FUSIONA las cabeceras de
    # ambos niveles, así que pasarla suelta mandaría las dos.
    async_auth_client.headers["X-Cascade-Owner"] = "otroowner0000000000000000000000b"
    ajenos = (await async_auth_client.get("/crawl-jobs")).json()

    assert ajenos == []


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

    # La carpeta lleva el nombre del paquete, saneado: un nombre con "../"
    # escaparía del volumen de descargas.
    import os
    assert os.path.basename(body["target_dir"]) == "p"
    assert ".." not in body["target_dir"]


@pytest.mark.asyncio
async def test_promoting_nothing_is_rejected(async_auth_client):
    created = await async_auth_client.post("/crawl-jobs", json={"links": "http://x/a.zip"})
    job_id = created.json()["id"]

    response = await async_auth_client.post(
        f"/crawl-jobs/{job_id}/promote", json={"name": "p", "result_ids": []}
    )

    assert response.status_code == 422
