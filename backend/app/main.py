from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.packages import router as packages_router
from app.api.settings import router as settings_router
from app.ws.routes import router as ws_router

app = FastAPI(title="Cascade")
app.include_router(auth_router)
app.include_router(packages_router)
app.include_router(settings_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
