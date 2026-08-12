import './StatusBadge.css'

type Tone = 'muted' | 'flow' | 'done' | 'warn' | 'fail'

/**
 * El mismo verbo en inglés significa cosas distintas según qué se esté
 * mirando: un paquete "running" está bajando, un análisis "running" está
 * buscando. Por eso el vocabulario se elige por contexto y no por estado.
 */
type Kind = 'transfer' | 'search'

const TRANSFER: Record<string, [string, Tone]> = {
  queued: ['en cola', 'muted'],
  running: ['bajando', 'flow'],
  paused: ['en pausa', 'warn'],
  completed: ['listo', 'done'],
  error: ['falló', 'fail'],
  canceled: ['cancelado', 'muted'],
}

const SEARCH: Record<string, [string, Tone]> = {
  pending: ['en cola', 'muted'],
  running: ['buscando', 'flow'],
  done: ['listo', 'done'],
  error: ['falló', 'fail'],
  ok: ['disponible', 'done'],
  dead: ['caído', 'fail'],
}

interface Props {
  status: string
  kind?: Kind
}

export default function StatusBadge({ status, kind = 'transfer' }: Props) {
  // Un estado que el backend agregue y esta tabla no conozca se muestra crudo:
  // preferible una palabra en inglés que una etiqueta que miente.
  const [label, tone] = (kind === 'search' ? SEARCH : TRANSFER)[status] ?? [status, 'muted']

  return (
    <span className={`status status--${tone}`}>
      <span className="status__mark" aria-hidden="true" />
      {label}
    </span>
  )
}
