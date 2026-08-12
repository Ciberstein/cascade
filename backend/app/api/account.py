"""Optional account: a way to recover this browser's token.

The account is **not** a front door. Cascade works without registering;
registering buys one thing: being able to recover the anonymous token from
another device, and so see the same download list there.

That is why there is no JWT and no session: the owner token is already the
credential, and the account is merely the way to get it back. `owner_id` never
changes on registration, so nothing already downloaded has to be migrated or
reassigned.
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
    """Whether this browser is registered, and under which name."""
    result = await db.execute(select(User).where(User.owner_id == owner))
    user = result.scalar_one_or_none()
    return AccountResponse(username=user.username if user else None)


@router.post("/register", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: CredentialsRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    """Ties this browser's token to a username and password.

    What has already been downloaded stays yours without moving a single row:
    the `owner_id` doesn't change, the account only makes it recoverable.
    """
    existing = await db.execute(select(User).where(User.owner_id == owner))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="This browser already has an account")

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
        raise HTTPException(status_code=409, detail="That username is already taken")

    return AccountResponse(username=payload.username)


@router.post("/login", response_model=OwnerTokenResponse)
async def login(payload: CredentialsRequest, db: AsyncSession = Depends(get_db)):
    """Returns that account's owner token, to be stored in this browser.

    Requires no owner header: this is precisely the case of a new device that
    doesn't have the right token yet.
    """
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    # The same message for a missing user and a wrong password: telling them
    # apart would confirm which names exist.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password")

    return OwnerTokenResponse(owner_token=user.owner_id)
