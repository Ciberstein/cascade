import { apiFetch } from './client'
import type { CrawlJob, Package } from '../types'

export function createCrawlJob(links: string): Promise<CrawlJob> {
  return apiFetch('/crawl-jobs', { method: 'POST', body: JSON.stringify({ links }) })
}

export function getCrawlJob(id: string): Promise<CrawlJob> {
  return apiFetch(`/crawl-jobs/${id}`)
}

/** Turns the chosen results into a downloadable package. */
export function promoteResults(
  jobId: string,
  name: string,
  resultIds: string[],
  /** Quality chosen per result. Anything missing uses the best available. */
  quality: Record<string, string> = {},
): Promise<Package> {
  return apiFetch(`/crawl-jobs/${jobId}/promote`, {
    method: 'POST',
    body: JSON.stringify({ name, result_ids: resultIds, quality }),
  })
}
