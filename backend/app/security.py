"""Hasheo de contraseñas para las cuentas opcionales."""

from passlib.context import CryptContext

_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _context.verify(password, password_hash)
