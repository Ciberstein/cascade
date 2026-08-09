export type ItemStatus = 'queued' | 'running' | 'paused' | 'completed' | 'error' | 'canceled'
export type PackageStatus = 'queued' | 'running' | 'paused' | 'completed' | 'error'

/** The subset of PackageStatus that PATCH /packages/{id} accepts. */
export type PackageAction = 'queued' | 'paused' | 'canceled'

export interface DownloadItem {
  id: string
  url: string
  filename: string
  status: ItemStatus
  /** Null until the initial probe reports Content-Length. */
  total_size: number | null
  downloaded_bytes: number
  error_message: string | null
  /** Qué plugin lo resolvió; 'direct' para un enlace directo. */
  hoster: string
  /** ISO 8601 mientras el hoster pide esperar; null en el caso normal. */
  retry_after: string | null
  /** El archivo ya se liberó del servidor; la fila queda en el historial. */
  file_removed: boolean
  /** 'video'/'audio' mientras se baja una calidad que vino en pistas separadas. */
  merge_role: string | null
}

export interface Package {
  id: string
  name: string
  status: PackageStatus
  target_dir: string
  items: DownloadItem[]
}

export interface AppSettings {
  max_concurrent_downloads: number
  chunks_per_file: number
  /** 0 means unlimited. */
  max_speed_kbps: number
  max_concurrent_crawls: number
}

export type CrawlJobStatus = 'pending' | 'running' | 'done' | 'error'
export type CrawlResultStatus = 'ok' | 'dead' | 'error'

export interface Variant {
  id: string
  label: string
  height: number | null
  size: number | null
  needs_merge: boolean
}

export interface CrawlResult {
  id: string
  url: string
  filename: string
  size: number | null
  hoster: string
  status: CrawlResultStatus
  error_message: string | null
  /** Calidades entre las que elegir. Vacío para lo que no es video. */
  variants: Variant[]
}

export interface CrawlJob {
  id: string
  raw_input: string
  status: CrawlJobStatus
  error_message: string | null
  results: CrawlResult[]
}
