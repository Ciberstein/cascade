import ProgressBar from './ProgressBar'
import StatusBadge from './StatusBadge'
import { formatBytes, percentOf } from '../format'
import type { Package } from '../types'
import './PackageRow.css'

interface Props {
  package: Package
  /** Live byte counts from the WS feed, fresher than the persisted ones. */
  progressByItemId?: Record<string, number>
  onPause: (id: string) => void
  onResume: (id: string) => void
  onCancel: (id: string) => void
  onOpen?: (id: string) => void
}

const FINISHED = new Set(['completed', 'error'])

export default function PackageRow({
  package: pkg,
  progressByItemId = {},
  onPause,
  onResume,
  onCancel,
  onOpen,
}: Props) {
  const totalSize = pkg.items.reduce((sum, i) => sum + (i.total_size ?? 0), 0)
  // The socket value wins when present: item.downloaded_bytes is only
  // checkpointed to the DB every few seconds, so a refetch mid-download would
  // otherwise pull the bar backwards to the last checkpoint.
  const downloaded = pkg.items.reduce(
    (sum, i) => sum + Math.max(i.downloaded_bytes, progressByItemId[i.id] ?? 0),
    0,
  )
  const percent = percentOf(downloaded, totalSize)
  const finished = FINISHED.has(pkg.status)

  // El primero que vuelve es el que define cuándo el paquete se mueve otra vez.
  const waitingUntil = pkg.items
    .map((i) => i.retry_after)
    .filter((value): value is string => value !== null)
    .sort()[0]

  return (
    <div className="package-row">
      <div className="package-row__header">
        {onOpen ? (
          <button className="package-row__name package-row__name--link" onClick={() => onOpen(pkg.id)}>
            {pkg.name}
          </button>
        ) : (
          <span className="package-row__name">{pkg.name}</span>
        )}
        <StatusBadge status={pkg.status} />
      </div>

      <ProgressBar
        percent={percent}
        caption={`${formatBytes(downloaded)} / ${formatBytes(totalSize || null)}`}
      />

      <div className="package-row__actions">
        {waitingUntil && (
          <span className="package-row__waiting">
            esperando hasta {new Date(waitingUntil).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
        {pkg.status === 'running' && <button onClick={() => onPause(pkg.id)}>Pausar</button>}
        {pkg.status === 'paused' && <button onClick={() => onResume(pkg.id)}>Reanudar</button>}
        {!finished && (
          <button className="package-row__danger" onClick={() => onCancel(pkg.id)}>
            Cancelar
          </button>
        )}
      </div>
    </div>
  )
}
