# Cascade

Pegás un enlace y recibís el archivo. El servidor lo baja por vos —con varias
conexiones en paralelo, reanudando si se corta, resolviendo el enlace real
detrás de la página— y te lo entrega al navegador. Después borra su copia.

Esa última parte es la idea entera: el servidor es un lugar de paso, no un
depósito. No hay carpeta que administrar ni archivos acumulándose en un disco
ajeno.

Tampoco hay login. Se entra y se usa.

---

## Cómo funciona para quien lo usa

**Pegar → elegir → recibir.**

1. Pegás una o varias URLs, una por línea.
2. Cascade mira qué hay detrás de cada una: si es un archivo directo, si es
   una carpeta abierta con veinte archivos adentro, si es un video con seis
   calidades. Te muestra lo que encontró.
3. Destildás lo que no querés, elegís calidad donde haya, y confirmás.
4. El archivo baja al servidor y, apenas termina, tu navegador se lo lleva
   solo a tu carpeta de descargas.

El historial vive en tu navegador, atado a un token anónimo. Registrarse es
**opcional** y sirve para una sola cosa: conservar esa lista y verla desde otro
dispositivo.

## Levantarlo

Requiere Docker.

```bash
cp .env.example .env      # poné una contraseña real en POSTGRES_PASSWORD
docker compose up -d --build
```

Queda en **http://127.0.0.1:8080**.

Escucha solo en localhost a propósito. Como no hay login, exponerlo en la red
le da a cualquiera la capacidad de encolar descargas y de cambiar los límites
del motor. Para abrirlo hay que decidirlo:

```bash
BIND_ADDRESS=0.0.0.0    # en el .env
```

Antes de hacer eso, leé [Lo que todavía no está](#lo-que-todavía-no-está).

## Qué hay adentro

Tres contenedores: `frontend` (nginx sirviendo la SPA y haciendo de proxy al
backend, así el WebSocket no necesita CORS), `backend` (FastAPI) y `postgres`.

El backend corre tres bucles en paralelo sobre el mismo evento de parada:

| Bucle | Qué hace |
|---|---|
| scheduler | toma items en cola y los baja en chunks paralelos |
| crawl | resuelve los enlaces pegados en archivos concretos |
| sweep | libera del disco lo ya entregado y lo que nadie retiró |

**El motor de descarga** parte cada archivo en chunks y los pide con `Range`.
Guarda el avance en la base recién después de vaciar el buffer a disco, así un
reinicio a mitad de camino reanuda desde un byte que realmente está escrito y
no desde uno que solo estaba en memoria. Hay límite de velocidad global por
token bucket.

**Las calidades separadas** (el 1080p de YouTube viene en dos pistas) se bajan
como dos items hermanos y se unen con `ffmpeg -c copy`, sin recodificar. La
pista de audio nunca se muestra como una descarga aparte: es un medio, no algo
que el usuario pidió.

**El borrado** tiene dos disparadores: 30 minutos después de que retirás el
archivo —no cero, porque si tu descarga se corta al 90% querés poder
reintentar— y un techo de 24 horas para lo que nadie fue a buscar.

### Estructura

```
backend/app/
  api/          endpoints: /packages /crawl-jobs /settings /account
  engine/       scheduler, chunker, downloader, rate limiter, merge
  crawler/      expansión de enlaces con recursión acotada
  plugins/      un archivo por hoster
  ws/           feed de progreso en vivo
frontend/src/
  components/   FlowRail (el medidor), Masthead, diálogos, filas
  pages/        Dashboard, LinkGrabber, PackageDetail, Settings, Account
docs/superpowers/   specs y planes de las dos fases
```

Las tipografías se sirven desde `frontend/public/fonts`, no desde un CDN: una
herramienta cuyo argumento es que no guarda nada tuyo no puede filtrar cada
visita a un tercero.

## Plugins

Cada hoster es un archivo en `backend/app/plugins/` que expone `PLUGIN`. El
registro los descubre solo al arrancar: agregar un hoster es agregar un
archivo, no editar una lista.

| Plugin | Cubre |
|---|---|
| `ytdlp` | ~1750 sitios de video, con sus calidades |
| `open_directory` | índices de Apache/nginx, recursivo hasta 3 niveles |
| `pixeldrain` | archivos y álbumes |
| `direct` | cualquier URL; va último y cierra la lista |

El contrato son dos operaciones. `crawl(url)` corre al pegar el enlace y
devuelve qué archivos hay detrás. `resolve(url, format_id)` corre justo antes
de bajar, porque las URLs directas de la mayoría de los hosters vencen en
minutos y una resuelta al pegar ya estaría muerta al llegar a la cola.

Los fallos se declaran con tipos —`LinkDead`, `UnsupportedLink`,
`RateLimited`— y cada uno lleva a una decisión distinta: descartar, seguir
probando con otro plugin, o reagendar para más tarde. Todo lo demás se envuelve
y se acota por timeout: un plugin colgado no se queda con un slot para siempre.

## Configuración

Del entorno (`.env`):

| Variable | Por defecto | Para qué |
|---|---|---|
| `POSTGRES_PASSWORD` | `cascade` | cambiala |
| `BIND_ADDRESS` | `127.0.0.1` | `0.0.0.0` lo abre a la red |

Desde la UI, en Configuración —y valen para el motor entero, no por usuario—:
descargas simultáneas (3), análisis simultáneos (5), chunks por archivo (4) y
límite de velocidad en KB/s (sin límite).

Los tiempos de retención se ajustan por entorno:
`RETRIEVAL_GRACE_MINUTES` (30) y `MAX_RETENTION_HOURS` (24).

## Desarrollo

```bash
# backend
cd backend
pip install -e ".[dev]"
pytest                     # los tests marcados 'live' quedan fuera
pytest -m live             # esos golpean sitios reales; corren a mano

# frontend
cd frontend
npm install
npm test
npm run dev                # servidor de Vite, proxy al backend en :8000
```

Los tests del backend corren sobre SQLite en memoria y producción es Postgres;
tenelo presente al tocar SQL crudo o tipos de columna, que es justo donde esa
diferencia se cobra.

La base se migra sola al arrancar el contenedor (`alembic upgrade head`).

## Lo que todavía no está

Honestidad sobre los bordes, porque el objetivo declarado es que esto sea una
herramienta pública y todavía no lo es:

- **SSRF.** El servidor busca la URL que le den. Nada le impide hoy pedir
  `http://169.254.169.254/` o cualquier cosa de la red interna. Es el motivo
  principal por el que el bind está en localhost.
- **Sin cuotas.** Nadie limita cuánto encola un visitante ni cuánto disco usa.
- **Los ajustes del motor son globales** y cualquiera que llegue a la UI puede
  cambiarlos. Deberían ser de operador.

## Licencia

MIT. Ver [LICENSE](LICENSE).
