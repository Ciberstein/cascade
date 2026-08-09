import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'
import * as packagesApi from './api/packages'
import * as socketHook from './ws/useProgressSocket'

afterEach(() => vi.restoreAllMocks())

test('goes straight to the dashboard, with no login in the way', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([])
  vi.spyOn(socketHook, 'useProgressSocket').mockReturnValue({ progressByItemId: {} })

  render(<App />)

  // Un login era una barrera para usar el servicio: se entra y ya.
  await waitFor(() => expect(screen.getByRole('button', { name: 'Agregar enlaces' })).toBeInTheDocument())
  expect(screen.queryByRole('button', { name: 'Ingresar' })).not.toBeInTheDocument()
})
