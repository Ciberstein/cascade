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
  /** Which plugin resolved it; 'direct' for a plain link. */
  hoster: string
  /** ISO 8601 while the hoster asks us to wait; null in the normal case. */
  retry_after: string | null
  /** The file has been freed from the server; the row stays in the history. */
  file_removed: boolean
  /** Already retrieved; the browser won't fire it again on its own. */
  retrieved: boolean
  /** 'video'/'audio' while downloading a quality that came as separate tracks. */
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
  /** Whether a cookie jar is stored. Never the jar: the API won't return it. */
  has_cookies?: boolean
  /** Only sent. Omitted leaves the stored jar alone; '' clears it. */
  hoster_cookies?: string
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
  /** Qualities to choose from. Empty for anything that isn't video. */
  variants: Variant[]
}

export interface CrawlJob {
  id: string
  raw_input: string
  status: CrawlJobStatus
  error_message: string | null
  results: CrawlResult[]
}
