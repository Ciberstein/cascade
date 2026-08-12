import { apiFetch } from './client'
import { setOwnerToken } from './owner'

export interface Account {
  username: string | null
}

/** The name this browser is registered under, or null if it isn't. */
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
 * Brings an account's download list into this browser.
 *
 * The account is not a front door: all it returns is the owner token, which is
 * stored here, and from then on this device sees that list.
 */
export async function login(username: string, password: string): Promise<void> {
  const { owner_token } = await apiFetch<{ owner_token: string }>('/account/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  setOwnerToken(owner_token)
}
