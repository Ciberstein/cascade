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

#: Más largo que esto no es una extensión, es un título con puntos.
_MAX_EXTENSION = 12


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
    return _truncate_keeping_extension(cleaned)


def _truncate_keeping_extension(name: str) -> str:
    """Recorta por el medio, no por el final, para no perder la extensión.

    Los títulos de video pasan de largo el límite con facilidad, y cortar a
    ciegas se lleva puesto el ".mp4": el archivo queda sin extensión y el
    sistema operativo no sabe con qué abrirlo.
    """
    if len(name) <= _MAX_FILENAME:
        return name

    stem, dot, ext = name.rpartition(".")
    # Sin punto, o con un "sufijo" tan largo que no puede ser una extensión
    # (un título con puntos en el medio), se recorta y ya.
    if not dot or not ext or len(ext) > _MAX_EXTENSION:
        return name[:_MAX_FILENAME]

    keep = _MAX_FILENAME - len(ext) - 1
    return f"{stem[:keep]}.{ext}"


def unique_name(name: str, taken: set[str]) -> str:
    """Agrega " (2)", " (3)"... si el nombre ya está usado, como un navegador.

    Respeta la extensión, que es lo que hace que el sufijo quede en
    "video (2).mp4" y no en "video.mp4 (2)".
    """
    if name not in taken:
        taken.add(name)
        return name

    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > _MAX_EXTENSION:
        stem, dot, ext = name, "", ""

    for n in range(2, 1000):
        candidate = f"{stem} ({n}){dot}{ext}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise ValueError(f"demasiados nombres repetidos como {name!r}")


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
