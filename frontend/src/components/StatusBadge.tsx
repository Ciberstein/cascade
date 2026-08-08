import './StatusBadge.css'

interface Props {
  status: string
}

/** Shows the raw backend status so the UI never disagrees with the API. */
export default function StatusBadge({ status }: Props) {
  return <span className={`badge badge--${status}`}>{status}</span>
}
