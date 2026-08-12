import FlowRail from './FlowRail'
import type { Flow } from './FlowRail'
import { fileUrl } from '../api/packages'
import StatusBadge from './StatusBadge'
import { formatBytes, percentOf } from '../format'
import type { Package } from '../types'
import './PackageRow.css'

interface Props {
  package: Package
  /** Live counts from the socket, fresher than the persisted ones. */
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
  // The socket value wins: item.downloaded_bytes is checkpointed every few
  // seconds, so a refetch mid-download would pull the rail backwards to the
  // last checkpoint.
  const downloaded = pkg.items.reduce(
    (sum, i) => sum + Math.max(i.downloaded_bytes, progressByItemId[i.id] ?? 0),
    0,
  )
  const percent = percentOf(downloaded, totalSize)
  const finished = FINISHED.has(pkg.status)

  // What the user can still take away. The audio track of a merge doesn't
  // count: it isn't a file they asked for.
  const own = pkg.items.filter((i) => i.merge_role !== 'audio')
  const retrievable = own.filter((i) => i.status === 'completed' && !i.file_removed)

  // Everything finished and the server holds nothing of this package any more.
  // It is the state that defines Cascade, so it gets said outright instead of
  // leaving the row on a "done" that suggests the file is still there.
  const released =
    own.length > 0 &&
    own.every((i) => i.status === 'completed') &&
    own.every((i) => i.file_removed)

  // The earliest one back is what decides when the package moves again. Only an
  // item that is genuinely still waiting counts: without filtering by status and
  // by expiry, an item that already finished would announce a wait forever, and
  // a stale mark would hide a sibling's real one.
  const now = Date.now()
  const waitingUntil = pkg.items
    .filter((i) => i.status === 'queued' && i.retry_after !== null)
    .map((i) => i.retry_after as string)
    .filter((value) => new Date(value).getTime() > now)
    .sort()[0]

  const state = flowOf(pkg.status, { released, waiting: Boolean(waitingUntil) })

  return (
    <article className="row">
      <FlowRail percent={percent} state={state} label={`Progress of ${pkg.name}`} />

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
            <span className="row__gone">delivered · the server let its copy go</span>
          ) : (
            <span>
              {formatBytes(downloaded)} / {formatBytes(totalSize || null)}
            </span>
          )}
          {waitingUntil && (
            <span className="row__note">
              waiting until{' '}
              {new Date(waitingUntil).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </p>

        <div className="row__actions">
          {/* In the list and not only in the detail view: this is where people
              look when a download finishes, and without it the file sits on the
              server until the sweep deletes it without anyone receiving it. */}
          {retrievable.length === 1 && (
            <a
              className="row__take"
              href={fileUrl(pkg.id, retrievable[0].id)}
              download={retrievable[0].filename}
            >
              Download
            </a>
          )}
          {retrievable.length > 1 && onOpen && (
            <button className="row__take" onClick={() => onOpen(pkg.id)}>
              Download {retrievable.length} files
            </button>
          )}
          {pkg.status === 'running' && (
            <button className="row__ctrl" onClick={() => onPause(pkg.id)}>
              Pause
            </button>
          )}
          {pkg.status === 'paused' && (
            <button className="row__ctrl" onClick={() => onResume(pkg.id)}>
              Resume
            </button>
          )}
          {/* "Stop" and not "Cancel": it sits next to Pause and has to read as
              the permanent one, and a dialog's dismiss button is also called
              Cancel - two of those on screen mean two different things. */}
          {!finished && (
            <button className="row__ctrl row__ctrl--danger" onClick={() => onCancel(pkg.id)}>
              Stop
            </button>
          )}
          {/* The row only announces the intention: who asks, and in what words,
              is decided by the Dashboard, where the dialogs live. */}
          <button className="row__ctrl" onClick={() => onRename(pkg.id)}>
            Rename
          </button>
          <button className="row__ctrl row__ctrl--danger" onClick={() => onDelete(pkg.id)}>
            Remove
          </button>
        </div>
      </div>
    </article>
  )
}

/** Maps the package status onto the flow, which draws more distinctions. */
function flowOf(status: string, ctx: { released: boolean; waiting: boolean }): Flow {
  if (status === 'error') return 'failed'
  if (status === 'paused') return 'stalled'
  if (status === 'completed') return ctx.released ? 'released' : 'done'
  // A wait the hoster asked for is neither a failure nor a pause the user
  // chose, but it is stopped flow, so it is painted as such.
  if (ctx.waiting) return 'stalled'
  if (status === 'running') return 'running'
  return 'queued'
}
