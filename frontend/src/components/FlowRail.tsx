import './FlowRail.css'

/**
 * The state of the flow, which is not the same as the state of the package.
 *
 * 'stalled' is a hoster that asked for time, and 'released' is what sets
 * Cascade apart from any other download manager: the file has been handed over
 * and the server deleted its copy, so the rail empties.
 */
export type Flow = 'queued' | 'running' | 'stalled' | 'done' | 'released' | 'failed'

interface Props {
  percent: number
  state: Flow
  /** What this rail measures, for anyone who can't see it. */
  label: string
}

export default function FlowRail({ percent, state, label }: Props) {
  const clamped = Math.max(0, Math.min(100, percent))
  // Emptying it is the correct reading: the rail measures what the server is
  // holding, and after delivery it holds nothing. The height transition does
  // the rest on its own once the poll brings the change in.
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
