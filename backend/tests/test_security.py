import pytest

from app.auth.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_and_verify_password():
    hashed = hash_password("hunter2")
    assert hashed != "hunter2"
    assert verify_password("hunter2", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_and_decode_access_token():
    # JWT_SECRET etc. come from the fixed test env vars set at the top of conftest.py —
    # security.py reads them into a module-level Settings() singleton at import time.
    token = create_access_token(subject="user-123")
    payload = decode_access_token(token)

    assert payload["sub"] == "user-123"


def test_decode_invalid_token_raises():
    with pytest.raises(Exception):
        decode_access_token("not-a-real-token")
