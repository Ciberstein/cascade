"""Anonymous per-browser identity.

There is no login: whoever arrives can use the service straight away. To know
which downloads to show them, the browser generates an opaque token, keeps it
in localStorage and sends it on every request.

That token *is* the identity: whoever holds it sees that history. Hence the
minimum length, so it cannot be guessed, and hence it is never logged. An
account is simply a token that can also be recovered from another device.
"""

from fastapi import Cookie, Header, HTTPException, status

OWNER_HEADER = "X-Cascade-Owner"
#: The same token, in a cookie. Needed because a download is an ordinary
#: browser navigation - an <a download> cannot send headers of its own - and
#: without this the endpoint that serves the file answered 400.
OWNER_COOKIE = "cascade_owner"

#: A uuid4 in hex is 32 characters. That is the floor, so the token cannot be
#: guessed: with no login, guessing it means reading someone else's history.
MIN_TOKEN_LENGTH = 32
MAX_TOKEN_LENGTH = 128


def _validate(token: str | None) -> str:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"missing {OWNER_HEADER} header",
        )
    if not (MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{OWNER_HEADER} must be between {MIN_TOKEN_LENGTH} and {MAX_TOKEN_LENGTH} characters",
        )
    if not token.isalnum():
        # Restricted to alphanumerics so nothing strange reaches queries or
        # logs; the client generates hexadecimal.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{OWNER_HEADER} accepts alphanumeric characters only",
        )
    return token


async def get_owner(
    x_cascade_owner: str | None = Header(default=None),
    cascade_owner: str | None = Cookie(default=None),
) -> str:
    """Who owns the data in this request.

    The header is the normal path (the API client sets it). The cookie covers
    browser navigations, which cannot carry headers of their own: downloading a
    file is exactly that case.
    """
    return _validate(x_cascade_owner or cascade_owner)


def owner_from_query(token: str | None) -> str | None:
    """Variant for the WebSocket, which cannot send headers of its own.

    Returns None instead of raising: the socket route closes the connection
    with its own code rather than answering with HTTP.
    """
    try:
        return _validate(token)
    except HTTPException:
        return None
