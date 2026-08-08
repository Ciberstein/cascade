const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const

/** Renders a byte count; null (size not probed yet) shows as an em dash. */
export function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—'

  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  // Bytes are always whole; larger units keep one decimal so a bar that is
  // visibly moving doesn't show a frozen number.
  return unit === 0 ? `${value} ${UNITS[unit]}` : `${value.toFixed(1)} ${UNITS[unit]}`
}

/** Aggregate completion as a 0-100 percentage; 0 when no size is known yet. */
export function percentOf(downloaded: number, total: number): number {
  if (total <= 0) return 0
  return Math.max(0, Math.min(100, (downloaded / total) * 100))
}
