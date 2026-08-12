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
  await vi.waitFor(() => expect(screen.getByText('bajando')).toBeInTheDocument())

  // The WS feed only carries byte counts - queued -> running -> completed
  // would otherwise sit stale on screen until the user reloaded the page.
  await vi.advanceTimersByTimeAsync(4000)
  await vi.waitFor(() => expect(screen.getByText('listo')).toBeInTheDocument())
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
  fireEvent.change(await screen.findByLabelText('Enlaces'), { target: { value: 'http://x/a.zip' } })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  // Pegar no crea un paquete: abre el análisis y el usuario confirma qué baja.
  await waitFor(() => expect(create).toHaveBeenCalledWith('http://x/a.zip'))
  expect(await screen.findByText('a.zip')).toBeInTheDocument()
})

test('keeps the pasted links on screen and shows why when the crawl job fails to create', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  vi.spyOn(crawlApi, 'createCrawlJob').mockRejectedValue(new Error('Carpeta de destino no escribible'))
  stubSocket()

  render(<Dashboard />)
  fireEvent.change(await screen.findByLabelText('Enlaces'), { target: { value: 'https://x/a.zip' } })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  // Cambiar de pantalla acá tiraría las URLs que el usuario acaba de pegar.
  expect(await screen.findByText('Carpeta de destino no escribible')).toBeInTheDocument()
  expect(screen.getByLabelText('Enlaces')).toHaveValue('https://x/a.zip')
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
          retry_after: null, file_removed: false, retrieved: false, merge_role: null,
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
  expect(await screen.findByLabelText('Enlaces')).toBeInTheDocument()
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
  await vi.waitFor(() => expect(screen.getByLabelText('Enlaces')).toBeInTheDocument())
})


test('deleting asks in the app, not in a browser popup', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([pkg])
  const remove = vi.spyOn(packagesApi, 'deletePackage').mockResolvedValue(undefined)
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Eliminar' }))

  // El diálogo nombra el paquete y aclara qué NO se pierde: "eliminar" suena a
  // que borra el archivo bajado, y no lo hace.
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('Pkg 1')
  expect(dialog).toHaveTextContent(/se queda donde está/)
  expect(remove).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: 'Quitar' }))
  await waitFor(() => expect(remove).toHaveBeenCalledWith('p1'))
})

test('backing out of the delete dialog deletes nothing', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([pkg])
  const remove = vi.spyOn(packagesApi, 'deletePackage').mockResolvedValue(undefined)
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Eliminar' }))
  fireEvent.keyDown(await screen.findByRole('dialog'), { key: 'Escape' })

  // Escape cierra, como en cualquier diálogo del sistema que este reemplaza.
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(remove).not.toHaveBeenCalled()
})

test('renaming carries the current name in and sends the trimmed one out', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([pkg])
  const rename = vi.spyOn(packagesApi, 'renamePackage').mockResolvedValue(pkg)
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Renombrar' }))

  // Entra escrito el nombre actual: renombrar suele ser retocar, no empezar
  // de cero.
  const field = await screen.findByLabelText('Nombre del paquete')
  expect(field).toHaveValue('Pkg 1')

  fireEvent.change(field, { target: { value: '  Backrooms  ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Guardar nombre' }))

  await waitFor(() => expect(rename).toHaveBeenCalledWith('p1', 'Backrooms'))
})

test('an empty name cannot be submitted', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([pkg])
  const rename = vi.spyOn(packagesApi, 'renamePackage').mockResolvedValue(pkg)
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Renombrar' }))
  fireEvent.change(await screen.findByLabelText('Nombre del paquete'), { target: { value: '   ' } })

  // La API lo rechaza; el botón muerto lo dice antes de viajar.
  expect(screen.getByRole('button', { name: 'Guardar nombre' })).toBeDisabled()
  fireEvent.keyDown(screen.getByLabelText('Nombre del paquete'), { key: 'Enter' })
  expect(rename).not.toHaveBeenCalled()
})
