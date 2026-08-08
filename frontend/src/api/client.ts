/** Thrown on 401 so the app shell can drop back to the login screen. */
export class UnauthorizedError extends Error {}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/**
 * Calls the backend on a relative path (same-origin in prod, proxied in dev).
 *
 * The session token lives in an httpOnly cookie, so there is no header to
 * attach here - `credentials: 'include'` is what makes the browser send it.
 */
export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })

  if (response.status === 401) {
    throw new UnauthorizedError('Not authenticated')
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response, path))
  }
  // PATCH/DELETE can answer 204; calling .json() on an empty body throws.
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

/**
 * Prefers FastAPI's `detail` field so the UI can show the real reason (a
 * duplicate URL, a bad target dir) instead of a bare status code. Anything
 * that isn't a json object with a string detail - an HTML error page from a
 * proxy, an empty body - falls back to the generic message rather than
 * letting the parse failure mask the original status.
 */
async function errorMessage(response: Response, path: string): Promise<string> {
  const fallback = `Request to ${path} failed with ${response.status}`
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const { detail } = body as { detail: unknown }
      if (typeof detail === 'string') {
        return detail
      }
    }
    return fallback
  } catch {
    return fallback
  }
}
