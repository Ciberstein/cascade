from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool = True


class UserOut(BaseModel):
    """Safe, public projection of a User -- excludes password_hash.

    Use this (or a hand-built dict) whenever a user-returning endpoint's
    response body is derived from a User ORM object. Never return the ORM
    object directly (e.g. via a loosely-scoped response_model or
    jsonable_encoder), since it serializes password_hash verbatim.
    """

    id: str
    username: str

    model_config = {"from_attributes": True}
