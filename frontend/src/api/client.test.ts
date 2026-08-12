import { afterEach, expect, test, vi } from 'vitest'
import { ApiError, apiFetch } from './client'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test('apiFetch returns parsed json', async () => {
  const mockFetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ hello: 'world' }),
  })
  vi.stubGlobal('fetch', mockFetch)

  const result = await apiFetch('/health')

  // No session cookie travels any more: the identity is the owner header.
  expect(mockFetch).toHaveBeenCalledWith('/health', expect.objectContaining({ headers: expect.any(Object) }))
  expect(result).toEqual({ hello: 'world' })
})

test('apiFetch sends the browser owner token', async () => {
  const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) })
  vi.stubGlobal('fetch', mockFetch)

  await apiFetch('/packages')

  // With no login, this header is the only thing telling the server whose
  // downloads it should return.
  const headers = mockFetch.mock.calls[0][1].headers
  expect(headers['X-Cascade-Owner']).toMatch(/^[0-9a-f]{32}$/)
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
