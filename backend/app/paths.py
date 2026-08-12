"""Path containment for remotely-sourced filenames.

A `filename` can come from the text of a link in someone else's HTML. Left
unsanitised, `os.path.join(package_dir, filename)` allows writing anywhere in
the container: `os.path.join` discards the whole prefix when the name is
absolute, and `..` escapes upwards. Since the engine then creates the directory
and writes bytes that the site also controls, that is enough to overwrite code
or scheduled jobs.
"""

import os
import re

#: Everything the filesystem treats as a separator, plus what is illegal on
#: Windows. Replaced rather than rejected: an odd name shouldn't block the
#: download, only stop being dangerous.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_MAX_FILENAME = 200

#: Longer than this is not an extension, it is a title with dots in it.
_MAX_EXTENSION = 12


def safe_filename(name: str, fallback: str = "download") -> str:
    """Reduces `name` to a filename that cannot leave its own folder.

    Keeps the last segment and neutralises the rest: "../../etc/passwd" becomes
    "passwd", "/etc/cron.d/x" becomes "x". Names that say nothing once cleaned
    ("", ".", "..") fall back to `fallback`.
    """
    # Split on both separators by hand: on Linux os.path.basename does not
    # treat "\" as a separator, so a name containing one would pass through
    # whole and turn dangerous again once the volume is mounted on Windows.
    last = re.split(r"[/\\]", name)[-1]
    cleaned = _UNSAFE.sub("_", last).strip().strip(".")

    if not cleaned:
        return fallback
    return _truncate_keeping_extension(cleaned)


def _truncate_keeping_extension(name: str) -> str:
    """Trims the middle, not the end, so the extension survives.

    Video titles overrun the limit easily, and cutting blindly takes the ".mp4"
    with it: the file ends up with no extension and the operating system has no
    idea what to open it with.
    """
    if len(name) <= _MAX_FILENAME:
        return name

    stem, dot, ext = name.rpartition(".")
    # With no dot, or with a "suffix" too long to be an extension (a title with
    # dots in the middle), just trim.
    if not dot or not ext or len(ext) > _MAX_EXTENSION:
        return name[:_MAX_FILENAME]

    keep = _MAX_FILENAME - len(ext) - 1
    return f"{stem[:keep]}.{ext}"


def unique_name(name: str, taken: set[str]) -> str:
    """Appends " (2)", " (3)"... when the name is taken, like a browser does.

    Respects the extension, which is what puts the suffix in "video (2).mp4"
    rather than "video.mp4 (2)".
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
    raise ValueError(f"too many repeated names like {name!r}")


def ensure_within(base_dir: str, path: str) -> str:
    """Returns `path` if it falls inside `base_dir`; raises ValueError if not.

    A second barrier, deliberately redundant with safe_filename: this one runs
    just before opening the file, so it also covers any path arriving through a
    route that doesn't exist yet, or one added later without remembering to
    sanitise.
    """
    base = os.path.realpath(base_dir)
    target = os.path.realpath(path)
    if base != target and not target.startswith(base + os.sep):
        raise ValueError(f"target path {path!r} falls outside {base_dir!r}")
    return path
