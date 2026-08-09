"""Identidad anónima por navegador.

No hay login: quien llega puede usar el servicio de inmediato. Para saber qué
descargas mostrarle, el navegador genera un token opaco, lo guarda en
localStorage y lo manda en cada request.

Ese token **es** la identidad: quien lo tenga ve ese historial. Por eso se
exige longitud suficiente para que no se pueda adivinar, y por eso nunca se
loguea. Cuando exista el registro de cuentas, una cuenta será simplemente un
token que además se puede recuperar desde otro dispositivo.
"""

from fastapi import Header, HTTPException, status

OWNER_HEADER = "X-Cascade-Owner"

#: Un uuid4 en hexadecimal son 32 caracteres. Se exige eso como piso para que
#: el token no sea adivinable: sin login, adivinarlo es acceder al historial
#: ajeno.
MIN_TOKEN_LENGTH = 32
MAX_TOKEN_LENGTH = 128


def _validate(token: str | None) -> str:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"falta la cabecera {OWNER_HEADER}",
        )
    if not (MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{OWNER_HEADER} debe tener entre {MIN_TOKEN_LENGTH} y {MAX_TOKEN_LENGTH} caracteres",
        )
    if not token.isalnum():
        # Acotado a alfanumérico para que no entre nada raro en consultas ni
        # en logs; el cliente genera hexadecimal.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{OWNER_HEADER} solo admite caracteres alfanuméricos",
        )
    return token


async def get_owner(x_cascade_owner: str | None = Header(default=None)) -> str:
    """Dueño de los datos de esta request."""
    return _validate(x_cascade_owner)


def owner_from_query(token: str | None) -> str | None:
    """Variante para el WebSocket, que no puede mandar cabeceras propias.

    Devuelve None en vez de lanzar: la ruta del socket cierra la conexión con
    su propio código en lugar de responder un HTTP.
    """
    try:
        return _validate(token)
    except HTTPException:
        return None
