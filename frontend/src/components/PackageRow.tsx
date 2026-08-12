import FlowRail from './FlowRail'
import type { Flow } from './FlowRail'
import { fileUrl } from '../api/packages'
import StatusBadge from './StatusBadge'
import { formatBytes, percentOf } from '../format'
import type { Package } from '../types'
import './PackageRow.css'

interface Props {
  package: Package
  /** Conteos vivos del socket, más frescos que los persistidos. */
  progressByItemId?: Record<string, number>
  onPause: (id: string) => void
  onResume: (id: string) => void
  onCancel: (id: string) => void
  onDelete: (id: string) => void
  onRename: (id: string) => void
  onOpen?: (id: string) => void
}

const FINISHED = new Set(['completed', 'error'])

export default function PackageRow({
  package: pkg,
  progressByItemId = {},
  onPause,
  onResume,
  onCancel,
  onDelete,
  onRename,
  onOpen,
}: Props) {
  const totalSize = pkg.items.reduce((sum, i) => sum + (i.total_size ?? 0), 0)
  // El valor del socket gana: item.downloaded_bytes se guarda cada varios
  // segundos, así que un refetch a mitad de descarga tiraría el riel hacia
  // atrás, hasta el último checkpoint.
  const downloaded = pkg.items.reduce(
    (sum, i) => sum + Math.max(i.downloaded_bytes, progressByItemId[i.id] ?? 0),
    0,
  )
  const percent = percentOf(downloaded, totalSize)
  const finished = FINISHED.has(pkg.status)

  // Lo que el usuario todavía puede llevarse. La pista de audio de una unión
  // no cuenta: no es un archivo que pidió.
  const own = pkg.items.filter((i) => i.merge_role !== 'audio')
  const retrievable = own.filter((i) => i.status === 'completed' && !i.file_removed)

  // Todo terminó y el servidor ya no guarda nada de este paquete. Es el estado
  // que define a Cascade, así que se dice con todas las letras en vez de
  // dejar la fila en un "listo" que sugiere que el archivo sigue ahí.
  const released =
    own.length > 0 &&
    own.every((i) => i.status === 'completed') &&
    own.every((i) => i.file_removed)

  // El primero que vuelve es el que define cuándo el paquete se mueve otra vez.
  // Solo cuenta un item que siga esperando de verdad: sin filtrar por estado y
  // por vencimiento, un item que ya terminó anunciaría una espera para siempre,
  // y una marca vieja taparía la espera real de un item hermano.
  const now = Date.now()
  const waitingUntil = pkg.items
    .filter((i) => i.status === 'queued' && i.retry_after !== null)
    .map((i) => i.retry_after as string)
    .filter((value) => new Date(value).getTime() > now)
    .sort()[0]

  const state = flowOf(pkg.status, { released, waiting: Boolean(waitingUntil) })

  return (
    <article className="row">
      <FlowRail percent={percent} state={state} label={`Progreso de ${pkg.name}`} />

      <div className="row__body">
        <div className="row__head">
          {onOpen ? (
            <button className="row__name" onClick={() => onOpen(pkg.id)}>
              {pkg.name}
            </button>
          ) : (
            <span className="row__name">{pkg.name}</span>
          )}
          <StatusBadge status={pkg.status} />
        </div>

        <p className="row__meter">
          <span className="row__pct">{Math.round(percent)}%</span>
          {released ? (
            <span className="row__gone">entregado · el servidor soltó su copia</span>
          ) : (
            <span>
              {formatBytes(downloaded)} / {formatBytes(totalSize || null)}
            </span>
          )}
          {waitingUntil && (
            <span className="row__note">
              esperando hasta{' '}
              {new Date(waitingUntil).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </p>

        <div className="row__actions">
          {/* En la lista y no solo en el detalle: es acá donde el usuario mira
              cuando una descarga termina, y sin esto el archivo se queda en el
              servidor hasta que el barrido lo borra sin que nadie lo haya
              recibido. */}
          {retrievable.length === 1 && (
            <a
              className="row__take"
              href={fileUrl(pkg.id, retrievable[0].id)}
              download={retrievable[0].filename}
            >
              Descargar
            </a>
          )}
          {retrievable.length > 1 && onOpen && (
            <button className="row__take" onClick={() => onOpen(pkg.id)}>
              Descargar {retrievable.length} archivos
            </button>
          )}
          {pkg.status === 'running' && (
            <button className="row__ctrl" onClick={() => onPause(pkg.id)}>
              Pausar
            </button>
          )}
          {pkg.status === 'paused' && (
            <button className="row__ctrl" onClick={() => onResume(pkg.id)}>
              Reanudar
            </button>
          )}
          {!finished && (
            <button className="row__ctrl row__ctrl--danger" onClick={() => onCancel(pkg.id)}>
              Cancelar
            </button>
          )}
          {/* La fila solo avisa la intención: quién pregunta y con qué palabras
              lo decide el Dashboard, que es donde viven los diálogos. */}
          <button className="row__ctrl" onClick={() => onRename(pkg.id)}>
            Renombrar
          </button>
          <button className="row__ctrl row__ctrl--danger" onClick={() => onDelete(pkg.id)}>
            Eliminar
          </button>
        </div>
      </div>
    </article>
  )
}

/** Traduce el estado del paquete al del caudal, que distingue más matices. */
function flowOf(status: string, ctx: { released: boolean; waiting: boolean }): Flow {
  if (status === 'error') return 'failed'
  if (status === 'paused') return 'stalled'
  if (status === 'completed') return ctx.released ? 'released' : 'done'
  // Una espera pedida por el hoster no es un fallo ni una pausa del usuario,
  // pero sí es caudal detenido: se pinta como tal.
  if (ctx.waiting) return 'stalled'
  if (status === 'running') return 'running'
  return 'queued'
}
