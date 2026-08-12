import './StatusBadge.css'

type Tone = 'muted' | 'flow' | 'done' | 'warn' | 'fail'

/**
 * The same verb means different things depending on what you are looking at: a
 * "running" package is downloading, a "running" analysis is searching. So the
 * vocabulary is chosen by context, not by status alone.
 */
type Kind = 'transfer' | 'search'

const TRANSFER: Record<string, [string, Tone]> = {
  queued: ['queued', 'muted'],
  running: ['downloading', 'flow'],
  paused: ['paused', 'warn'],
  completed: ['done', 'done'],
  error: ['failed', 'fail'],
  canceled: ['canceled', 'muted'],
}

const SEARCH: Record<string, [string, Tone]> = {
  pending: ['queued', 'muted'],
  running: ['searching', 'flow'],
  done: ['done', 'done'],
  error: ['failed', 'fail'],
  ok: ['available', 'done'],
  dead: ['dead', 'fail'],
}

interface Props {
  status: string
  kind?: Kind
}

export default function StatusBadge({ status, kind = 'transfer' }: Props) {
  // A status the backend adds that this table doesn't know is shown raw: a word
  // the UI doesn't understand beats a label that lies.
  const [label, tone] = (kind === 'search' ? SEARCH : TRANSFER)[status] ?? [status, 'muted']

  return (
    <span className={`status status--${tone}`}>
      <span className="status__mark" aria-hidden="true" />
      {label}
    </span>
  )
}
