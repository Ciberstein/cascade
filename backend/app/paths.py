"""Contención de rutas para nombres de archivo de origen remoto.

Un `filename` puede venir del texto de un enlace en el HTML de un sitio ajeno.
Sin sanear, `os.path.join(package_dir, filename)` deja escribir en cualquier
parte del contenedor: `os.path.join` descarta el prefijo entero si el nombre
es absoluto, y `..` escapa hacia arriba. Como el motor después crea el
directorio y escribe bytes también controlados por el sitio, eso alcanza para
sobrescribir código o tareas programadas.
"""

import os
import re

#: Todo lo que el sistema de archivos trata como separador o es ilegal en
#: Windows. Se reemplaza en vez de rechazar: un nombre raro no debería
#: impedir la descarga, solo dejar de ser peligroso.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_MAX_FILENAME = 200


def safe_filename(name: str, fallback: str = "download") -> str:
    """Reduce `name` a un nombre de archivo que no puede salir de su carpeta.

    Se queda con el último segmento y neutraliza el resto: "../../etc/passwd"
    queda en "passwd", "/etc/cron.d/x" en "x". Los nombres que después de
    limpiar no dicen nada ("", ".", "..") caen en `fallback`.
    """
    # Se parte por ambos separadores a mano: en Linux os.path.basename no
    # trata "\" como separador, así que un nombre con "\" pasaría entero y
    # volvería a ser peligroso al montarse el volumen en Windows.
    last = re.split(r"[/\\]", name)[-1]
    cleaned = _UNSAFE.sub("_", last).strip().strip(".")

    if not cleaned:
        return fallback
    return cleaned[:_MAX_FILENAME]


def ensure_within(base_dir: str, path: str) -> str:
    """Devuelve `path` si cae dentro de `base_dir`; si no, lanza ValueError.

    Segunda barrera, deliberadamente redundante con safe_filename: esta se
    aplica justo antes de abrir el archivo, así que cubre también cualquier
    ruta que llegue por un camino que todavía no exista o que se agregue más
    adelante sin recordar sanear.
    """
    base = os.path.realpath(base_dir)
    target = os.path.realpath(path)
    if base != target and not target.startswith(base + os.sep):
        raise ValueError(f"la ruta de destino {path!r} queda fuera de {base_dir!r}")
    return path
