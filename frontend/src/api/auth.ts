import { apiFetch } from './client'

/**
 * Rejects with UnauthorizedError on bad credentials - at the login screen that
 * means "wrong username/password", not "your session expired".
 */
export function login(username: string, password: string): Promise<{ ok: boolean }> {
  return apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}

export function me(): Promise<{ username: string }> {
  return apiFetch('/auth/me')
}
