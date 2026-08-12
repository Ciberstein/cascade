import { apiFetch } from './client'
import type { CrawlJob, Package } from '../types'

export function createCrawlJob(links: string): Promise<CrawlJob> {
  return apiFetch('/crawl-jobs', { method: 'POST', body: JSON.stringify({ links }) })
}

export function getCrawlJob(id: string): Promise<CrawlJob> {
  return apiFetch(`/crawl-jobs/${id}`)
}

/** Convierte los resultados elegidos en un paquete descargable. */
export function promoteResults(
  jobId: string,
  name: string,
  resultIds: string[],
  /** Calidad elegida por resultado. Lo que falte usa la mejor disponible. */
  quality: Record<string, string> = {},
): Promise<Package> {
  return apiFetch(`/crawl-jobs/${jobId}/promote`, {
    method: 'POST',
    body: JSON.stringify({ name, result_ids: resultIds, quality }),
  })
}
