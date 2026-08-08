import './ProgressBar.css'

interface Props {
  percent: number
  /** Rendered next to the percentage, e.g. "400 MB / 1.0 GB". */
  caption?: string
}

export default function ProgressBar({ percent, caption }: Props) {
  const clamped = Math.max(0, Math.min(100, percent))
  const rounded = Math.round(clamped)

  return (
    <div className="progress">
      <div
        className="progress__track"
        role="progressbar"
        aria-valuenow={rounded}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="progress__fill" style={{ width: `${clamped}%` }} />
      </div>
      <div className="progress__labels">
        <span>{rounded}%</span>
        {caption && <span className="progress__caption">{caption}</span>}
      </div>
    </div>
  )
}
