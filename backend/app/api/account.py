"""Cuenta opcional: una forma de recuperar el token de este navegador.

La cuenta **no** es una puerta de entrada. Se puede usar Cascade sin
registrarse; registrarse sirve para una sola cosa: poder recuperar el token
anónimo desde otro dispositivo y así ver ahí la misma lista de descargas.

Por eso no hay JWT ni sesión: el token de dueño ya es la credencial, y la
cuenta es apenas la manera de volver a obtenerlo. `owner_id` nunca cambia al
registrarse, así que no hay que migrar ni re-asignar nada de lo ya descargado.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.owner import get_owner
from app.schemas import AccountResponse, CredentialsRequest, OwnerTokenResponse
from app.security import hash_password, verify_password

router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_model=AccountResponse)
async def whoami(db: AsyncSession = Depends(get_db), owner: str = Depends(get_owner)):
    """Si este navegador ya está registrado, con qué nombre."""
    result = await db.execute(select(User).where(User.owner_id == owner))
    user = result.scalar_one_or_none()
    return AccountResponse(username=user.username if user else None)


@router.post("/register", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: CredentialsRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    """Ata el token de este navegador a un usuario y contraseña.

    Lo ya descargado sigue siendo tuyo sin mover un solo registro: el
    `owner_id` no cambia, la cuenta solo lo vuelve recuperable.
    """
    existing = await db.execute(select(User).where(User.owner_id == owner))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Este navegador ya tiene una cuenta")

    db.add(
        User(
            username=payload.username,
            password_hash=hash_password(payload.password),
            owner_id=owner,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está tomado")

    return AccountResponse(username=payload.username)


@router.post("/login", response_model=OwnerTokenResponse)
async def login(payload: CredentialsRequest, db: AsyncSession = Depends(get_db)):
    """Devuelve el token de dueño de esa cuenta, para guardarlo en este navegador.

    No exige cabecera de dueño: es justamente el caso de un dispositivo nuevo
    que todavía no tiene el token correcto.
    """
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    # Mismo mensaje para usuario inexistente y contraseña incorrecta: distinguirlos
    # confirmaría qué nombres existen.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    return OwnerTokenResponse(owner_token=user.owner_id)
