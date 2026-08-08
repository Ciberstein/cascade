import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Dashboard from './Dashboard'
import * as packagesApi from '../api/packages'
import * as socketHook from '../ws/useProgressSocket'
import { UnauthorizedError } from '../api/client'
import type { Package } from '../types'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function stubSocket(progressByItemId: Record<string, number> = {}, unauthorized = false) {
  vi.spyOn(socketHook, 'useProgressSocket').mockReturnValue({ progressByItemId, unauthorized })
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

test('creates a package from the modal and refreshes', async () => {
  const list = vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  const create = vi.spyOn(packagesApi, 'createPackage').mockResolvedValue(pkg)
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Agregar enlaces' }))

  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: 'https://x/a.zip' } })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar' }))

  await waitFor(() => expect(create).toHaveBeenCalledWith('Paquete sin nombre', ['https://x/a.zip']))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(list.mock.calls.length).toBeGreaterThan(1)
})

test('keeps the modal open and shows why when creation fails', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  vi.spyOn(packagesApi, 'createPackage').mockRejectedValue(new Error('Carpeta de destino no escribible'))
  stubSocket()

  render(<Dashboard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Agregar enlaces' }))
  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: 'https://x/a.zip' } })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar' }))

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

test('reports an expired session to the shell', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockRejectedValue(new UnauthorizedError('nope'))
  stubSocket()
  const onUnauthorized = vi.fn()

  render(<Dashboard onUnauthorized={onUnauthorized} />)

  await waitFor(() => expect(onUnauthorized).toHaveBeenCalled())
})

test('reports an expired session detected by the socket', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  stubSocket({}, true)
  const onUnauthorized = vi.fn()

  render(<Dashboard onUnauthorized={onUnauthorized} />)

  await waitFor(() => expect(onUnauthorized).toHaveBeenCalled())
})
