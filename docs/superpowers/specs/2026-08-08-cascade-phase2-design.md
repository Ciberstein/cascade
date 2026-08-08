# Cascade — Fase 2: Sistema de plugins para hosters

**Fecha**: 2026-08-08
**Estado**: Aprobado para planificación

## Contexto

Fase 1 entregó el motor core: descarga segmentada por chunks con `Range`, cola con scheduler y límite de concurrencia, checkpointing y reanudación tras reinicio, límite global de velocidad, progreso en vivo por WebSocket y UI web con login. Hoy solo sirve para enlaces directos: la URL que pega el usuario es la que se descarga.

Fase 2 agrega la capa que convierte un enlace de hoster en algo descargable, que es lo que separa a Cascade de `wget` y la primera fase que lo acerca de verdad a JDownloader.

Fase 1 dejó el hueco previsto para esto: `identity: Callable[[str], str]` en `backend/app/engine/scheduler.py`, con un placeholder `_identity` en `backend/app/main.py`. Ese hueco resultó estar en el lugar correcto (ver "Las dos operaciones del plugin").

## Alcance

**Dentro:**

- Framework de plugins de hosters: contrato, registro, descubrimiento, aislamiento de fallos.
- Resolución de enlaces de un clic (sin cuenta).
- Expansión de carpetas/álbumes: un link de entrada produce N archivos.
- Chequeo de enlaces: nombre, tamaño y vivo/muerto antes de encolar.
- Esperas y límites por IP: un item puede agendarse para más tarde en vez de fallar.
- LinkGrabber: bandeja donde se revisan y confirman los resultados antes de descargar.

**Fuera (con su razón):**

- **Cuentas premium** → Fase 2b. Es un subsistema aparte: credenciales cifradas en reposo, estado de sesión por hoster, expiración y límites de cuenta, y su propia UI. Meterlo acá obligaría a diseñar dos subsistemas a la vez.
- **Hosters con criptografía propia** (Mega y similares) → más adelante. No le piden nada nuevo al framework: son plugins con más código adentro. Diferirlos no hipoteca el diseño.
- **Sitios que exigen ejecutar JavaScript** → más adelante. Requieren un navegador headless (Playwright): +400 MB de imagen, consumo de RAM que cambia el perfil del despliegue, y una superficie de fallo nueva. No se puede agregar a medias: o está en la imagen o no está. El contrato del resolver se diseña `async` y sin presuponer que resolver es rápido, para que un plugin con navegador entre después sin romperlo.
- **CAPTCHA** → Fase 3, como ya preveía el roadmap.

### Expectativa realista sobre "parecido a JDownloader"

El valor de JDownloader son sus cientos de plugins mantenidos por una comunidad, no su arquitectura. Un proyecto self-hosted no va a igualar esa cobertura, y perseguirla es una trampa. El entregable que importa es un framework donde **agregar un hoster sea escribir unas decenas de líneas y un test**, de modo que cuando un sitio cambia y el plugin se rompe —, y se rompen seguido —, arreglarlo sea trivial y el resto siga funcionando.

## Decisiones clave

- **Descubrimiento al agregar (modelo LinkGrabber)**: el usuario pega links, se crawlean en segundo plano, revisa qué archivos aparecieron y confirma cuáles encolar. Ojo con el vocabulario: lo que ocurre al agregar es el **crawleo** (qué hay detrás del link), no la resolución de la URL directa, que ocurre al descargar por las razones de la sección siguiente.
- **Plugins como módulos Python en el repo**, descubiertos automáticamente, cada uno con sus tests. Arreglar un plugin es un commit y un rebuild.
- **El grabber es un subsistema propio**: tablas propias, loop propio, y un paso explícito de promoción a `packages`/`download_items`. El scheduler de descargas no cambia su contrato.

### Alternativas descartadas

**Reusar `download_items` con un estado `grabbed`.** Menos tablas y sin paso de copia, pero hoy el scheduler levanta todo lo que esté en `queued` y el dashboard lista todos los paquetes. Cada consulta existente pasaría a necesitar un filtro, y olvidar uno significa que un link a medio resolver se empieza a descargar solo. Es la clase de bug silencioso que costó encontrar en Fase 1: un contrato simple al que se le agregan excepciones.

**Resolver en línea dentro de `POST /packages`.** Nada nuevo que construir, pero un request que tarda 30 segundos o más se cae solo, y no deja bandeja de confirmación.

**Plugins en una carpeta externa montada por volumen.** Permite parchear en caliente sin rebuildear, pero es ejecutar código arbitrario dentro del proceso de la app y deja los plugins fuera del control de versiones y de los tests. El registro queda diseñado de forma que agregarlo después sea posible si el rebuild llega a molestar.

**Plugins declarativos (YAML con regex y selectores).** Limpio para casos simples, pero cualquier hoster con token de un solo uso o flujo de dos pasos no entra, y el final previsible es inventar un lenguaje de programación en YAML.

## Las dos operaciones del plugin

Crawlear y resolver no son la misma operación y no pueden ocurrir en el mismo momento.

```python
class Hoster(Protocol):
    name: str

    def can_handle(self, url: str) -> bool: ...

    # Al agregar: qué archivos hay detrás de este link.
    async def crawl(self, url: str) -> CrawlResult: ...

    # Al descargar: dame la URL directa, ahora.
    async def resolve(self, url: str) -> DirectLink: ...
```

`crawl` corre en el LinkGrabber y descubre nombre, tamaño y si el link está vivo. `resolve` corre justo antes de descargar y devuelve la URL directa más los headers y cookies que esa URL necesite.

**Por qué separados: las URLs directas caducan.** Casi todo hoster las firma con un token de un solo uso o con TTL de minutos. Resolver todo al agregar dejaría una cola de 40 archivos con 39 URLs vencidas antes de llegar a ellas. JDownloader hace este mismo corte por el mismo motivo.

Consecuencia práctica: `resolve` entra exactamente donde Fase 1 dejó `identity`. El motor de descargas no se rediseña. Lo único que cambia es que ese seam pasa a ser `async` y a devolver headers además de la URL.

El temporizador de espera vive en `resolve`, que es cuando la espera sirve.

### Tipos de retorno

```python
@dataclass
class CrawlResult:
    files: list[CrawledFile]   # 0..N — una carpeta expande a muchos
    children: list[str]        # links que a su vez hay que crawlear

@dataclass
class CrawledFile:
    url: str
    filename: str
    size: int | None           # None si el hoster no lo informa
    alive: bool

@dataclass
class DirectLink:
    url: str
    headers: dict[str, str]    # cookies, referer, lo que la URL exija
```

El chequeo de enlaces no es una operación aparte: es el resultado de `crawl`. Un archivo con `alive=False` se guarda como `crawl_results.status = 'dead'`; una excepción del plugin lo guarda como `'error'` con su mensaje. Es decir, "chequear si el link vive" y "ver qué hay detrás del link" son la misma llamada, que es precisamente por qué las tres capacidades del alcance comparten un solo contrato.

## Modelo de datos

Dos tablas nuevas:

| Tabla | Campos |
|---|---|
| `crawl_jobs` | `id`, `raw_input` (el texto pegado), `status` (`pending`/`running`/`done`/`error`), `created_at`, `error_message` |
| `crawl_results` | `id`, `crawl_job_id`, `url`, `filename`, `size`, `hoster`, `status` (`ok`/`dead`/`error`), `error_message` |

La selección de qué descargar **no se persiste**: vive en el cliente y viaja como lista de ids al confirmar. Una columna `selected` solo agregaría estado que mantener sincronizado sin que nadie lo consulte después.

Dos columnas nuevas en `download_items`:

- **`hoster`** — qué plugin resolvió el link, para saber a cuál llamar al descargar. Nunca nulo: un enlace directo queda como `direct`, un plugin interno que devuelve la URL tal cual. Así el enlace directo de Fase 1 deja de ser un caso especial y el código no necesita ramas para "con plugin" y "sin plugin".
- **`retry_after`** (`datetime | None`) — el cambio estructural en la cola.

Una columna nueva en `settings`: **`max_concurrent_crawls`**.

### Esperas en la cola

La consulta del scheduler pasa de:

```sql
status = 'queued'
```

a:

```sql
status = 'queued' AND (retry_after IS NULL OR retry_after <= now())
```

Un item en espera **sigue en `queued`**, no en un estado nuevo. Para la cola es trabajo pendiente que todavía no toca; modelarlo como estado aparte obligaría a moverlo de ida y de vuelta con dos transiciones más que pueden fallar.

### Recursión en carpetas

El crawler recursa sobre `children` con un límite de profundidad configurable en código (no expuesto en la UI), y escribe en `crawl_results` solo los archivos finales. El límite existe porque un link mal formado que se apunta a sí mismo es, sin tope, un bucle infinito que consume la cola.

## Flujo de datos

1. El usuario pega uno o más links → `POST /crawl-jobs` crea el job en `pending`.
2. El loop de crawl lo toma, y para cada link busca plugin en el registro y llama a `crawl`.
3. Los `children` se crawlean recursivamente hasta el límite de profundidad; los archivos finales se escriben como `crawl_results`.
4. El job pasa a `done`. La UI, que venía consultando, muestra la tabla.
5. El usuario elige qué bajar → `POST /crawl-jobs/{id}/promote` con los ids y el nombre del paquete → crea `package` + `download_items` con su `hoster`.
6. El scheduler los levanta como cualquier item de Fase 1. Antes de descargar llama a `resolve` del plugin correspondiente.
7. Si `resolve` señala una espera, el item vuelve a `queued` con `retry_after`; el scheduler lo saltea hasta que venza.

## Ejecución

**Loop de crawl**: segundo loop de fondo en el lifespan, con la misma forma que el del scheduler —, un tick que toma trabajo pendiente y se traga sus propios errores para que un fallo no mate el loop, y parada ordenada por flag (no `task.cancel()`, por lo aprendido en Fase 1: cancelar puede caer dentro de un `commit` y dejar la conexión a medias). Su propio límite `max_concurrent_crawls`, más alto que el de descargas, porque crawlear es esperar respuestas cortas y no satura ni disco ni ancho de banda.

**Registro de plugins**: descubre los módulos de `app/plugins/` al arrancar; cada módulo expone una instancia `PLUGIN`. El match es por orden con `direct` siempre último como red de seguridad. Agregar un hoster es agregar un archivo, sin registro manual.

**Timeout por llamada**: todo `crawl` y todo `resolve` corre bajo `asyncio.wait_for`. Un plugin colgado contra un sitio caído se queda con un slot para siempre, y con límite de concurrencia unos pocos links muertos congelarían la cola entera.

## Manejo de errores

Los plugins comunican qué pasó con excepciones tipadas:

| Excepción | Consecuencia |
|---|---|
| `LinkDead` | Marca el link como muerto. No reintenta: no va a revivir. |
| `RateLimited(retry_at)` | Vuelve a `queued` con `retry_after`. No es un error, es trabajo agendado. |
| `UnsupportedLink` | El registro sigue probando; termina en `direct`. |
| `PluginError(msg)` | Falla el item, con el mensaje visible en la UI. |
| Cualquier otra | Se captura y se loguea como `PluginError`. |

La última fila es deliberada. Un plugin es código de terceros corriendo dentro del proceso; asumir que solo lanza las excepciones documentadas es exactamente cómo un hoster roto se lleva puesta la cola. Es la misma disciplina que ya aplica `_run_one_item` en Fase 1.

Errores heredados de Fase 1 que siguen valiendo: chunk fallido con backoff, disco lleno, reinicio a mitad de descarga.

## UI

**Cambio de comportamiento**: el modal "Agregar enlaces" de Fase 1 deja de crear un paquete directamente y pasa a crear un `crawl_job`, llevando al usuario a la bandeja. Es una modificación sobre algo que ya funciona y debe quedar explícita en el plan de implementación.

**Bandeja (LinkGrabber)**: pantalla nueva con la tabla de resultados —, casilla, nombre, tamaño, hoster, estado. Los links muertos aparecen marcados y **sin tildar por defecto**: verlos importa porque dice qué se perdió de la lista pegada, pero tildarlos solo encola un fallo garantizado. Al confirmar se pide nombre de paquete y se vuelve al dashboard.

**Dashboard**: un item con `retry_after` muestra "esperando hasta HH:MM", no un error. La diferencia entre "esto se rompió" y "esto está agendado" es lo que evita que el usuario cancele descargas que iban bien.

**Actualizaciones**: polling, igual que ya hace el dashboard con las transiciones de estado. El WebSocket existe para el chorro de bytes de la descarga, que es alta frecuencia; un crawl que dura segundos y termina no justifica un tipo de mensaje nuevo.

**Settings**: se agrega el control de `max_concurrent_crawls`.

## Testing

- **Plugins contra HTML guardado en el repo.** Es la pieza central: cuando el sitio cambia el parser y el plugin se rompe, el aviso llega por un test que falla y no por una descarga que falla de madrugada.
- **Límite reconocido**: un fixture es una foto. Prueba que el parser entiende la página capturada, no la que el sitio sirve hoy. Ningún test offline detecta que el hoster cambió el HTML anoche. Por eso el plan incluye (a) una forma documentada de re-capturar fixtures y (b) tests marcados que golpean el sitio real, excluidos de la corrida normal, para ejecutar a mano ante la sospecha de una rotura.
- **Registro**: matching por orden, fallback a `direct`, plugin inexistente.
- **Loop de crawl**: contra el `FlakyTestServer` que ya existe en `backend/tests/fixtures/`, extendido si hace falta.
- **Recursión**: una carpeta que expande a N archivos; un link que se apunta a sí mismo corta en el límite de profundidad.
- **Temporizador**: un item con `retry_after` futuro se saltea; con `retry_after` pasado se levanta.
- **Timeout**: un plugin que se cuelga no retiene el slot.
- **Frontend**: pantalla de bandeja con la API mockeada; el dashboard mostrando el estado de espera.

## Fuera de alcance (heredado del roadmap)

- Cuentas premium → Fase 2b.
- Resolución de CAPTCHA → Fase 3.
- Extracción de archivos y contenedores cifrados → Fase 4.
- Multi-usuario / SaaS, link grabbing desde portapapeles o extensión de navegador.
