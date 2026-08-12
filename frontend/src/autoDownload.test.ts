import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { autoDownloadFinished } from './autoDownload'
import type { Package } from './types'

let clicked: { href: string; download: string }[]

beforeEach(() => {
  clicked = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.getAttribute('href') ?? '', download: this.download })
  })
})

afterEach(() => vi.restoreAllMocks())

function item(over: Partial<Package['items'][0]> = {}): Package['items'][0] {
  return {
    id: 'i1', url: 'http://x/a', filename: 'a.zip', status: 'completed',
    total_size: 10, downloaded_bytes: 10, error_message: null, hoster: 'direct',
    retry_after: null, file_removed: false, retrieved: false, merge_role: null,
    ...over,
  }
}

function pkg(items: Package['items']): Package {
  return { id: 'p1', name: 'p', status: 'completed', target_dir: '/x', items }
}

test('a finished file downloads itself', () => {
  autoDownloadFinished([pkg([item()])], new Set())

  expect(clicked).toEqual([{ href: '/packages/p1/items/i1/file', download: 'a.zip' }])
})

test('a file still downloading is left alone', () => {
  autoDownloadFinished([pkg([item({ status: 'running' })])], new Set())

  expect(clicked).toEqual([])
})

test('a file already retrieved is not fetched again', () => {
  // El servidor lo marca al entregarlo; sin esto cada sondeo volvería a
  // dispararlo y el navegador bajaría el mismo archivo una y otra vez.
  autoDownloadFinished([pkg([item({ retrieved: true })])], new Set())

  expect(clicked).toEqual([])
})

test('the same file is not triggered twice by two polls in a row', () => {
  const triggered = new Set<string>()

  autoDownloadFinished([pkg([item()])], triggered)
  // Segundo sondeo antes de que el servidor alcance a marcarlo retirado.
  autoDownloadFinished([pkg([item()])], triggered)

  expect(clicked).toHaveLength(1)
})

test('a file the server already released is not requested', () => {
  autoDownloadFinished([pkg([item({ file_removed: true })])], new Set())

  expect(clicked).toEqual([])
})

test('the audio track of a merge is never downloaded on its own', () => {
  // Es un medio para conseguir el archivo, no un archivo que el usuario pidió.
  autoDownloadFinished([pkg([item({ merge_role: 'audio' })])], new Set())

  expect(clicked).toEqual([])
})
