import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Login from './Login'
import * as authApi from '../api/auth'

afterEach(() => vi.restoreAllMocks())

test('submits credentials and calls onSuccess', async () => {
  const loginSpy = vi.spyOn(authApi, 'login').mockResolvedValue({ ok: true })
  const onSuccess = vi.fn()

  render(<Login onSuccess={onSuccess} />)

  fireEvent.change(screen.getByLabelText('Usuario'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'hunter2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))

  await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  expect(loginSpy).toHaveBeenCalledWith('admin', 'hunter2')
})

test('shows error message on failed login', async () => {
  vi.spyOn(authApi, 'login').mockRejectedValue(new Error('bad creds'))

  render(<Login onSuccess={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Usuario'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'wrong' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))

  expect(await screen.findByText('Usuario o contraseña incorrectos')).toBeInTheDocument()
})

test('clears a stale error when the next attempt succeeds', async () => {
  const loginSpy = vi
    .spyOn(authApi, 'login')
    .mockRejectedValueOnce(new Error('bad creds'))
    .mockResolvedValueOnce({ ok: true })

  render(<Login onSuccess={vi.fn()} />)
  const submit = screen.getByRole('button', { name: 'Ingresar' })

  fireEvent.click(submit)
  expect(await screen.findByRole('alert')).toBeInTheDocument()

  fireEvent.click(submit)
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(loginSpy).toHaveBeenCalledTimes(2)
})

test('disables the submit button while the request is in flight', async () => {
  let resolveLogin: (value: { ok: boolean }) => void = () => {}
  vi.spyOn(authApi, 'login').mockReturnValue(
    new Promise((resolve) => {
      resolveLogin = resolve
    }),
  )

  render(<Login onSuccess={vi.fn()} />)
  const submit = screen.getByRole('button', { name: 'Ingresar' })

  fireEvent.click(submit)

  // Without this, an impatient double-click fires a second login round-trip.
  await waitFor(() => expect(submit).toBeDisabled())
  resolveLogin({ ok: true })
})
