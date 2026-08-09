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

  // El registro no puede parecer un requisito: la razón de sacar el login era
  // que nada se interponga entre llegar y usar.
  expect(await screen.findByText(/Cascade funciona sin registrarse/)).toBeInTheDocument()
})

test('registering keeps the current list', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: null })
  const registerSpy = vi.spyOn(accountApi, 'register').mockResolvedValue({ username: 'daniel' })

  render(<Account onClose={noop} onIdentityChanged={noop} />)
  await screen.findByLabelText('Usuario')

  fireEvent.change(screen.getByLabelText('Usuario'), { target: { value: 'daniel' } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'una-clave-larga' } })
  fireEvent.click(screen.getByRole('button', { name: /Registrarme/ }))

  await waitFor(() => expect(registerSpy).toHaveBeenCalledWith('daniel', 'una-clave-larga'))
  // Queda mostrando la cuenta, no un formulario vacío.
  expect(await screen.findByText('daniel')).toBeInTheDocument()
})

test('logging in swaps the identity and tells the shell to reload', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: null })
  const loginSpy = vi.spyOn(accountApi, 'login').mockResolvedValue(undefined)
  const onIdentityChanged = vi.fn()

  render(<Account onClose={noop} onIdentityChanged={onIdentityChanged} />)
  await screen.findByLabelText('Usuario')

  fireEvent.change(screen.getByLabelText('Usuario'), { target: { value: 'daniel' } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'una-clave-larga' } })
  fireEvent.click(screen.getByRole('button', { name: /Entrar/ }))

  await waitFor(() => expect(loginSpy).toHaveBeenCalledWith('daniel', 'una-clave-larga'))
  // La lista en pantalla es la del token viejo: hay que recargarla.
  await waitFor(() => expect(onIdentityChanged).toHaveBeenCalled())
})

test('an already-registered browser is told so instead of asked again', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: 'daniel' })

  render(<Account onClose={noop} onIdentityChanged={noop} />)

  expect(await screen.findByText('daniel')).toBeInTheDocument()
  expect(screen.queryByLabelText('Contraseña')).not.toBeInTheDocument()
})

test('a failed registration shows why', async () => {
  vi.spyOn(accountApi, 'getAccount').mockResolvedValue({ username: null })
  vi.spyOn(accountApi, 'register').mockRejectedValue(new Error('Ese nombre de usuario ya está tomado'))

  render(<Account onClose={noop} onIdentityChanged={noop} />)
  await screen.findByLabelText('Usuario')

  fireEvent.click(screen.getByRole('button', { name: /Registrarme/ }))

  expect(await screen.findByText('Ese nombre de usuario ya está tomado')).toBeInTheDocument()
})
