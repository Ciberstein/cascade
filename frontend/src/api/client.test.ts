import { afterEach, expect, test, vi } from 'vitest'
import { ApiError, apiFetch, UnauthorizedError } from './client'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test('apiFetch includes credentials and returns parsed json', async () => {
  const mockFetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ hello: 'world' }),
  })
  vi.stubGlobal('fetch', mockFetch)

  const result = await apiFetch('/health')

  expect(mockFetch).toHaveBeenCalledWith('/health', expect.objectContaining({ credentials: 'include' }))
  expect(result).toEqual({ hello: 'world' })
})

test('apiFetch throws UnauthorizedError on 401', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) }))

  await expect(apiFetch('/packages')).rejects.toBeInstanceOf(UnauthorizedError)
})

test('apiFetch surfaces the API detail message on other errors', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: 'URL already queued in this package' }),
    }),
  )

  // The UI shows this text verbatim, so FastAPI's `detail` has to survive the
  // client layer rather than being flattened into a bare status code.
  await expect(apiFetch('/packages')).rejects.toThrow('URL already queued in this package')
})

test('apiFetch falls back to a generic message when the error body is not json', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new SyntaxError('Unexpected token < in JSON')
      },
    }),
  )

  // A 502 from a proxy returns HTML, not json; the parse failure must not
  // replace the real status with a confusing SyntaxError.
  const error = await apiFetch('/packages').catch((e: unknown) => e)
  expect(error).toBeInstanceOf(ApiError)
  expect((error as ApiError).status).toBe(500)
})

test('apiFetch returns undefined for 204 responses', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 204, json: async () => ({}) }))

  await expect(apiFetch('/packages/abc')).resolves.toBeUndefined()
})
