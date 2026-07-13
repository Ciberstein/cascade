from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password, verify_password
from app.config import Settings
from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])
_settings = Settings()


async def _get_or_create_admin(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.username == _settings.admin_username))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(
        username=_settings.admin_username,
        password_hash=hash_password(_settings.admin_password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        result = await db.execute(select(User).where(User.username == _settings.admin_username))
        user = result.scalar_one()
    else:
        await db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await _get_or_create_admin(db)
    if payload.username != user.username or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(subject=user.id)
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=_settings.jwt_expire_minutes * 60,
    )
    return LoginResponse()
