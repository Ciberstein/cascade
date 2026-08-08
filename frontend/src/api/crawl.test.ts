import { afterEach, expect, test, vi } from 'vitest'
import { createCrawlJob, getCrawlJob, promoteResults } from './crawl'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function stubFetch(body: unknown) {
  const mock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body })
  vi.stubGlobal('fetch', mock)
  return mock
}

test('createCrawlJob posts the raw pasted text', async () => {
  const mock = stubFetch({ id: 'j1', raw_input: 'http://x/a', status: 'pending', results: [] })

  await createCrawlJob('http://x/a')

  expect(mock).toHaveBeenCalledWith(
    '/crawl-jobs',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ links: 'http://x/a' }) }),
  )
})

test('getCrawlJob fetches a single job by id', async () => {
  const mock = stubFetch({ id: 'j1', raw_input: '', status: 'done', results: [] })

  await getCrawlJob('j1')

  expect(mock).toHaveBeenCalledWith('/crawl-jobs/j1', expect.anything())
})

test('promoteResults sends the package name and the chosen ids', async () => {
  const mock = stubFetch({ id: 'p1', name: 'Mi paquete', status: 'queued', target_dir: '/x', items: [] })

  await promoteResults('j1', 'Mi paquete', ['r1', 'r2'])

  expect(mock).toHaveBeenCalledWith(
    '/crawl-jobs/j1/promote',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ name: 'Mi paquete', result_ids: ['r1', 'r2'] }),
    }),
  )
})
