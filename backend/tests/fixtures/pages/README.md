# Páginas guardadas

Cada archivo de esta carpeta es una captura real de un hoster, usada por los
tests de plugins para correr sin red.

**Son fotos.** Prueban que el parser entiende la página que capturamos, no la
que el sitio sirve hoy. Un plugin puede estar roto en producción con todos sus
tests en verde. Contra eso están los tests de `backend/tests/live/`.

## Re-capturar una página

```bash
curl -sL "https://ejemplo.com/carpeta/" -o backend/tests/fixtures/pages/<nombre>.html
```

Después de re-capturar, correr los tests del plugin correspondiente. Si fallan,
el sitio cambió y hay que actualizar el parser — que es exactamente lo que la
captura sirve para detectar.

Quitar de la página guardada cualquier token de sesión o dato personal antes de
commitearla.

## Correr los tests contra los sitios reales

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -m live tests/live -v
```

Salen a internet y pueden fallar por causas ajenas al código (el hoster caído,
el archivo canario borrado). Por eso están fuera de la corrida normal.
