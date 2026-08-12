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

  // A login was a barrier to using the service: you arrive and go, with the
  // field for pasting links already on screen.
  await waitFor(() => expect(screen.getByLabelText('Links')).toBeInTheDocument())
  expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
})
