import { apiFetch } from './client'
import { setOwnerToken } from './owner'

export interface Account {
  username: string | null
}

/** Con qué nombre está registrado este navegador, o null si no lo está. */
export function getAccount(): Promise<Account> {
  return apiFetch('/account')
}

export function register(username: string, password: string): Promise<Account> {
  return apiFetch('/account/register', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

/**
 * Recupera en este navegador la lista de descargas de una cuenta.
 *
 * La cuenta no es una puerta de entrada: lo único que devuelve es el token de
 * dueño, que se guarda acá y a partir de ahí este dispositivo ve esa lista.
 */
export async function login(username: string, password: string): Promise<void> {
  const { owner_token } = await apiFetch<{ owner_token: string }>('/account/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  setOwnerToken(owner_token)
}
