import { ownerToken } from './owner'

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
 * There is no login: the owner header is what identifies this browser and
 * decides which downloads the server returns.
 */
export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Cascade-Owner': ownerToken(),
      ...options.headers,
    },
  })

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
