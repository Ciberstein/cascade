# Cascade — Fase 1: Motor core + UI web básica

**Fecha**: 2026-07-13
**Estado**: Aprobado para planificación

## Contexto y propósito

Cascade es un gestor de descargas self-hosted, 100% web (sin cliente de escritorio), inspirado en JDownloader. El objetivo final (multi-fase) es replicar el alcance completo de JDownloader: descarga multi-conexión, plugins para cientos de hosters, resolución de CAPTCHA, extracción de archivos y contenedores cifrados.

Dado el tamaño del alcance completo, el proyecto se divide en fases, cada una con su propio spec e implementación:

1. **Fase 1 (este documento)**: motor core de descargas (cola, multi-conexión por chunks, pausa/resume) + UI web básica para enlaces directos.
2. **Fase 2**: sistema de plugins para hosters (resolución de enlaces protegidos/ofuscados por sitio).
3. **Fase 3**: resolución de CAPTCHA.
4. **Fase 4**: extracción de archivos (RAR, etc.) y contenedores cifrados (RSDF/CCF/DLC o equivalentes propios).

Este spec cubre únicamente la Fase 1.

## Decisiones clave

- **Despliegue**: self-hosted, un solo usuario, empaquetado en Docker Compose.
- **Frontend**: React + Vite (SPA).
- **Backend**: Python + FastAPI, proceso único con motor de descargas basado en `asyncio`/`httpx` (ver "Arquitectura del motor" más abajo para las alternativas descartadas).
- **Persistencia**: PostgreSQL.
- **Progreso en tiempo real**: WebSocket autenticado, throttled (~500ms) por conexión.
- **Autenticación**: usuario único (creado por variables de entorno en el primer arranque), login con usuario/contraseña, sesión JWT en cookie httpOnly.
- **Descarga segmentada**: cada archivo se divide en N chunks paralelos vía HTTP `Range` requests, con fallback a un solo chunk si el servidor no soporta `Range`.

## Arquitectura del motor de descargas

Se evaluaron tres opciones para la concurrencia del motor:

- **FastAPI + asyncio nativo (elegida)**: un solo proceso/contenedor maneja API, WebSocket y descargas concurrentes vía tareas `asyncio`. Menor complejidad operativa, ideal para un solo usuario self-hosted. El progreso se sincroniza a PostgreSQL cada pocos segundos (checkpoint), por lo que un crash del proceso pierde a lo sumo unos segundos de progreso visual, nunca bytes ya escritos a disco.
- **FastAPI + Celery + Redis**: patrón estándar para escalar a multi-worker/multi-usuario, pero suma 2 servicios más al despliegue sin beneficio para el caso de uso actual (un solo usuario). Descartada para Fase 1; candidata natural si el proyecto migra a un modelo multi-usuario en el futuro.
- **FastAPI + arq (Redis async ligero)**: punto intermedio, descartada por la misma razón (servicio extra sin beneficio claro todavía).

## Arquitectura general

```
┌─────────────────┐        HTTPS/WSS        ┌──────────────────────────┐
│  React + Vite    │ <──────────────────────> │   FastAPI (1 proceso)    │
│  (SPA)            │   REST (CRUD) + WS       │  - API REST              │
└─────────────────┘   (progreso en vivo)      │  - WebSocket broadcaster │
                                               │  - Motor de descargas    │
                                               │    (asyncio + httpx)     │
                                               └──────────┬───────────────┘
                                                          │
                                               ┌──────────▼───────────────┐
                                               │      PostgreSQL          │
                                               │ (paquetes, items,        │
                                               │  progreso, usuario)      │
                                               └───────────────────────────┘
                                                          │
                                               ┌──────────▼───────────────┐
                                               │  Volumen de descargas    │
                                               │  (disco montado)         │
                                               └───────────────────────────┘
```

Docker Compose con 2 servicios: `app` (FastAPI, sirviendo también el build estático de React) y `postgres`. Volúmenes separados para la DB y para los archivos descargados.

## Componentes

### Backend (Python/FastAPI)
- `api/` — endpoints REST: auth, paquetes (CRUD), configuración.
- `ws/` — manejo de conexiones WebSocket y broadcast de eventos de progreso.
- `engine/`:
  - `scheduler` — arranca paquetes/items respetando el límite de descargas simultáneas configurado.
  - `downloader` — por archivo: `HEAD`/`GET` inicial para tamaño y soporte de `Range`, división en chunks, descarga paralela con reintentos, ensamblado del archivo final.
  - `progress_tracker` — agrega progreso de chunk → item → paquete y lo envía al broadcaster.
- `models/` — entidades SQLAlchemy.
- `auth/` — login, JWT, hash de contraseña.

### Frontend (React/Vite)
- Login.
- Dashboard: lista de paquetes con progreso en vivo y controles (pausa/resume/cancelar).
- Modal "Agregar enlaces": textarea para pegar una o más URLs, nombre de paquete opcional.
- Detalle de paquete: progreso por archivo individual.
- Configuración: carpeta de descarga, descargas simultáneas máximas, chunks por archivo, límite de ancho de banda global.

## Modelo de datos (PostgreSQL)

- **`user`**: `id`, `username`, `password_hash`.
- **`package`**: `id`, `name`, `status` (queued/running/paused/completed/error), `created_at`, `target_dir`.
- **`download_item`**: `id`, `package_id`, `url`, `filename`, `total_size`, `status` (queued/running/paused/completed/error/canceled), `downloaded_bytes`, `error_message`, `retries`.
- **`chunk`**: `id`, `download_item_id`, `range_start`, `range_end`, `downloaded_bytes`, `status` (pending/running/completed/failed). Persistido para permitir reanudar tras un reinicio sin re-descargar bytes ya obtenidos.
- **`settings`**: carpeta de descarga por defecto, descargas simultáneas máximas, chunks por archivo, límite de velocidad global (KB/s, 0 = sin límite).

`downloaded_bytes` de `chunk` se actualiza en memoria a alta frecuencia y se sincroniza a la DB cada ~2-3s (checkpoint), no en cada byte.

## Flujo de datos (caso típico)

1. El usuario pega una o más URLs en "Agregar enlaces" → `POST /packages` crea el `package` y sus `download_item` en estado `queued`.
2. El `scheduler` detecta items `queued` y, respetando el límite de concurrencia, arranca cada uno: `HEAD`/`GET` inicial para `total_size` y soporte de `Range`; si hay soporte, crea N chunks; si no, 1 solo chunk.
3. Cada chunk se descarga en una tarea `asyncio` independiente, escribiendo directo en su posición del archivo final (pre-allocado en disco).
4. El `progress_tracker` agrega bytes de chunk → item → paquete; el broadcaster WS empuja updates a los clientes conectados (throttled ~500ms).
5. Al completar todos los chunks de un item, se verifica el tamaño final y se marca `completed`. Al completar todos los items de un paquete, el paquete pasa a `completed`.
6. Pausa/cancelación (`PATCH`): cancela las tareas `asyncio` activas del item, dejando el progreso de cada chunk persistido para reanudar después desde el offset guardado vía `Range`.

## Manejo de errores

- **Chunk fallido** (timeout, conexión cortada, 5xx): reintento con backoff exponencial (hasta 3 intentos), reanudando desde `downloaded_bytes` guardado.
- **Sin soporte de `Range`**: fallback automático a un solo chunk.
- **URL inválida / sin respuesta al `HEAD` inicial**: item pasa a `error` con `error_message` visible en la UI; no bloquea el resto del paquete.
- **Disco lleno**: detectado al escribir, item pasa a `error`, notificado por WS; el resto de descargas continúa.
- **Reinicio del servidor a mitad de descarga**: al arrancar, el scheduler re-encola items en `running`, reanudando cada chunk desde su checkpoint persistido.
- **URLs duplicadas** dentro de un paquete activo: se avisa en la UI en vez de crear un duplicado silencioso.

## Testing

- **Backend (pytest)**: lógica del engine aislada (división en chunks, backoff, transiciones de estado, checkpoint/resume) contra un servidor HTTP local de prueba que simula soporte/no-soporte de `Range` y fallos intermitentes.
- **Integración**: flujo completo API → engine → DB con descargas reales contra el servidor de prueba local (sin depender de internet).
- **Frontend**: tests de componentes (agregar enlaces, tabla de progreso, controles) con WebSocket mockeado.
- **E2E (Playwright, opcional en Fase 1)**: login → agregar URL → ver progreso → completar, contra el stack completo en Docker Compose.

## Fuera de alcance (Fase 1)

- Plugins de hosters (Fase 2).
- Resolución de CAPTCHA (Fase 3).
- Extracción de archivos y contenedores cifrados (Fase 4).
- Multi-usuario / SaaS.
- Link grabbing desde portapapeles o extensión de navegador.
