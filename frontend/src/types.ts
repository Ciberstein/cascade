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
}

export interface Package {
  id: string
  name: string
  status: PackageStatus
  target_dir: string
  items: DownloadItem[]
}

export interface AppSettings {
  download_root: string
  max_concurrent_downloads: number
  chunks_per_file: number
  /** 0 means unlimited. */
  max_speed_kbps: number
}
