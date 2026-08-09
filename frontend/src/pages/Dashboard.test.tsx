import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Dashboard from './Dashboard'
import * as packagesApi from '../api/packages'
import * as crawlApi from '../api/crawl'
import * as settingsApi from '../api/settings'
import * as socketHook from '../ws/useProgressSocket'
import type { Package } from '../types'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function stubSocket(progressByItemId: Record<string, number> = {}) {
  vi.spyOn(socketHook, 'useProgressSocket').mockReturnValue({ progressByItemId })
}

const pkg: Package = { id: 'p1', name: 'Pkg 1', status: 'running', target_dir: '/x', items: [] }

test('loads and renders packages on mount', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([pkg])
  stubSocket()

  render(<Dashboard />)

  await waitFor(() => expect(screen.getByText('Pkg 1')).toBeInTheDocument())
})

test('shows an empty state when there are no packages', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  stubSocket()

  render(<Dashboard />)

  expect(await screen.findByText(/No hay descargas/)).toBeInTheDocument()
})

test('refetches so status transitions appear without a reload', async () => {
  vi.useFakeTimers()
  const list = vi
    .spyOn(packagesApi, 'listPackages')
    .mockResolvedValueOnce([pkg])
    .mockResolvedValue([{ ...pkg, status: 'completed' }])
  stubSocket()

  render(<Dashboard />)
  await vi.waitFor(() => expect(screen.getByText('running')).toBeInTheDocument())

  // The WS feed only carries byte counts - queued -> running -> completed
  // would otherwise sit stale on screen until the user reloaded the page.
  await vi.advanceTimersByTimeAsync(4000)
  await vi.waitFor(() => expect(screen.getByText('completed')).toBeInTheDocument())
  expect(list.mock.calls.length).toBeGreaterThan(1)
})

test('pasting links creates a crawl job and opens the tray', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  const create = vi.spyOn(crawlApi, 'createCrawlJob').mockResolvedValue({
    id: 'j1', raw_input: 'http://x/a.zip', status: 'pending', error_message: null, results: [],
  })
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue({
    id: 'j1', raw_input: 'http://x/a.zip', status: 'done', error_message: null,
    results: [{ id: 'r1', url: 'http://x/a.zip', filename: 'a.zip', size: 10, hoster: 'direct', status: 'ok', error_message: null, variants: [] }],
  })
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Agregar enlaces' }))
  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: 'http://x/a.zip' } })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  // El modal ya no crea un paquete: ahora abre el análisis y el usuario
  // confirma qué baja.
  await waitFor(() => expect(create).toHaveBeenCalledWith('http://x/a.zip'))
  expect(await screen.findByText('a.zip')).toBeInTheDocument()
})

test('keeps the modal open and shows why when the crawl job fails to create', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  vi.spyOn(crawlApi, 'createCrawlJob').mockRejectedValue(new Error('Carpeta de destino no escribible'))
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Agregar enlaces' }))
  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: 'https://x/a.zip' } })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  // Closing the modal here would throw away the URLs the user just pasted.
  expect(await screen.findByText('Carpeta de destino no escribible')).toBeInTheDocument()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
})

test('maps the pause control to the status the API accepts', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([pkg])
  const update = vi.spyOn(packagesApi, 'updatePackageStatus').mockResolvedValue(pkg)
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Pausar' }))

  await waitFor(() => expect(update).toHaveBeenCalledWith('p1', 'paused'))
})

test('clicking a package name shows its detail view', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([
    {
      ...pkg,
      items: [
        {
          id: 'i1',
          url: 'https://x/a.zip',
          filename: 'a.zip',
          status: 'running',
          total_size: 100,
          downloaded_bytes: 10,
          error_message: null,
          hoster: 'direct',
          retry_after: null, file_removed: false, merge_role: null,
        },
      ],
    },
  ])
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByText('Pkg 1'))

  expect(await screen.findByText('a.zip')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Volver' })).toBeInTheDocument()
})

test('opens and closes the settings view', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue({
    max_concurrent_downloads: 3,
    chunks_per_file: 4,
    max_speed_kbps: 0,
    max_concurrent_crawls: 5,
  })
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Configuración' }))

  fireEvent.click(await screen.findByRole('button', { name: 'Cancelar' }))
  expect(await screen.findByRole('button', { name: 'Agregar enlaces' })).toBeInTheDocument()
})

test('falls back to the list when the open package disappears', async () => {
  // Nothing deletes packages in Fase 1, but the detail view resolves its
  // package from the polled list - it must not render a dead screen if a poll
  // ever comes back without it.
  vi.useFakeTimers()
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValueOnce([pkg]).mockResolvedValue([])
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await vi.waitFor(() => screen.getByText('Pkg 1')))
  expect(screen.getByRole('button', { name: 'Volver' })).toBeInTheDocument()

  await vi.advanceTimersByTimeAsync(4000)
  await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Agregar enlaces' })).toBeInTheDocument())
})

