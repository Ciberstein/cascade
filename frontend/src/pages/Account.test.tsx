import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Account from './Account'
import * as accountApi from '../api/account'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

const noop = () => {}

test('says the account is optional, because it is', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: null })

  render(<Account onClose={noop} onIdentityChanged={noop} />)

  // Registering must not look like a requirement: the reason the login went
  // away was so nothing stands between arriving and using it.
  expect(await screen.findByText(/Cascade works without an account/)).toBeInTheDocument()
})

test('registering keeps the current list', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: null })
  const registerSpy = vi.spyOn(accountApi, 'register').mockResolvedValue({ username: 'daniel' })

  render(<Account onClose={noop} onIdentityChanged={noop} />)
  await screen.findByLabelText('Username')

  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'daniel' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'una-clave-larga' } })
  fireEvent.click(screen.getByRole('button', { name: /Register/ }))

  await waitFor(() => expect(registerSpy).toHaveBeenCalledWith('daniel', 'una-clave-larga'))
  // It ends up showing the account, not an empty form.
  expect(await screen.findByText('daniel')).toBeInTheDocument()
})

test('logging in swaps the identity and tells the shell to reload', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: null })
  const loginSpy = vi.spyOn(accountApi, 'login').mockResolvedValue(undefined)
  const onIdentityChanged = vi.fn()

  render(<Account onClose={noop} onIdentityChanged={onIdentityChanged} />)
  await screen.findByLabelText('Username')

  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'daniel' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'una-clave-larga' } })
  fireEvent.click(screen.getByRole('button', { name: /Sign in/ }))

  await waitFor(() => expect(loginSpy).toHaveBeenCalledWith('daniel', 'una-clave-larga'))
  // The list on screen belongs to the old token: it has to be reloaded.
  await waitFor(() => expect(onIdentityChanged).toHaveBeenCalled())
})

test('an already-registered browser is told so instead of asked again', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: 'daniel' })

  render(<Account onClose={noop} onIdentityChanged={noop} />)

  expect(await screen.findByText('daniel')).toBeInTheDocument()
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
})

test('a failed registration shows why', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: null })
  vi.spyOn(accountApi, 'register').mockRejectedValue(new Error('That username is already taken'))

  render(<Account onClose={noop} onIdentityChanged={noop} />)
  await screen.findByLabelText('Username')

  fireEvent.click(screen.getByRole('button', { name: /Register/ }))

  expect(await screen.findByText('That username is already taken')).toBeInTheDocument()
})
