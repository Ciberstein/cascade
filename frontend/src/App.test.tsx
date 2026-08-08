import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'
import * as authApi from './api/auth'
import * as packagesApi from './api/packages'
import * as socketHook from './ws/useProgressSocket'
import { UnauthorizedError } from './api/client'

afterEach(() => vi.restoreAllMocks())

function stubDashboardDeps() {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  vi.spyOn(socketHook, 'useProgressSocket').mockReturnValue({
    progressByItemId: {},
    unauthorized: false,
  })
}

test('shows login when not authenticated', async () => {
  vi.spyOn(authApi, 'me').mockRejectedValue(new UnauthorizedError('401'))
  stubDashboardDeps()

  render(<App />)

  await waitFor(() => expect(screen.getByRole('button', { name: 'Ingresar' })).toBeInTheDocument())
})

test('shows dashboard when already authenticated', async () => {
  vi.spyOn(authApi, 'me').mockResolvedValue({ username: 'admin' })
  stubDashboardDeps()

  render(<App />)

  await waitFor(() => expect(screen.getByText('Agregar enlaces')).toBeInTheDocument())
})

test('drops back to login when the session expires mid-session', async () => {
  vi.spyOn(authApi, 'me').mockResolvedValue({ username: 'admin' })
  vi.spyOn(packagesApi, 'listPackages').mockRejectedValue(new UnauthorizedError('expired'))
  vi.spyOn(socketHook, 'useProgressSocket').mockReturnValue({
    progressByItemId: {},
    unauthorized: false,
  })

  render(<App />)

  // The JWT outlives the tab; without this the dashboard would poll forever
  // against a session the backend has already rejected.
  await waitFor(() => expect(screen.getByRole('button', { name: 'Ingresar' })).toBeInTheDocument())
})

test('switches to the dashboard after a successful login', async () => {
  vi.spyOn(authApi, 'me').mockRejectedValue(new UnauthorizedError('401'))
  vi.spyOn(authApi, 'login').mockResolvedValue({ ok: true })
  stubDashboardDeps()

  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'Ingresar' }))

  await waitFor(() => expect(screen.getByText('Agregar enlaces')).toBeInTheDocument())
})
