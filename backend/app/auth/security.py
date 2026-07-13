import datetime as dt

from jose import jwt
from passlib.context import CryptContext

from app.config import Settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_settings = Settings()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


def create_access_token(subject: str) -> str:
    expire = dt.datetime.utcnow() + dt.timedelta(minutes=_settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, _settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _settings.jwt_secret, algorithms=[ALGORITHM])
