import './FlowRail.css'

/**
 * Estado del caudal, que no es lo mismo que el estado del paquete.
 *
 * 'stalled' es la espera de un hoster que pidió tiempo, y 'released' es lo que
 * distingue a Cascade de cualquier otro gestor: el archivo ya se entregó y el
 * servidor borró su copia, así que el riel se vacía.
 */
export type Flow = 'queued' | 'running' | 'stalled' | 'done' | 'released' | 'failed'

interface Props {
  percent: number
  state: Flow
  /** Qué mide este riel, para quien no lo ve. */
  label: string
}

export default function FlowRail({ percent, state, label }: Props) {
  const clamped = Math.max(0, Math.min(100, percent))
  // Vaciarlo es la lectura correcta: el riel mide lo que el servidor tiene en
  // la mano, y tras la entrega no tiene nada. La transición de altura hace el
  // resto sola cuando el sondeo trae el cambio.
  const filled = state === 'released' ? 0 : clamped

  return (
    <div
      className={`rail rail--${state}`}
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className="rail__fill" style={{ height: `${filled}%` }} />
    </div>
  )
}
