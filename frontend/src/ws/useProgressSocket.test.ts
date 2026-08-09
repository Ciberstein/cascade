import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { useProgressSocket } from './useProgressSocket'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onmessage: ((ev: { data: string }) => void) | null = null
  onopen: (() => void) | null = null
  onclose: ((ev: { code: number }) => void) | null = null
  close = vi.fn()
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
}

afterEach(() => {
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

test('updates progress map when a message arrives', () => {
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)

  const { result } = renderHook(() => useProgressSocket())
  const socket = FakeWebSocket.instances[0]

  act(() => {
    socket.onmessage?.({
      data: JSON.stringify({ type: 'progress', item_id: 'item-1', downloaded_bytes: 500 }),
    })
  })

  expect(result.current.progressByItemId['item-1']).toBe(500)
})

test('closes the socket on unmount', () => {
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)

  const { unmount } = renderHook(() => useProgressSocket())
  const socket = FakeWebSocket.instances[0]

  unmount()

  expect(socket.close).toHaveBeenCalled()
})

test('ignores malformed frames instead of tearing down the hook', () => {
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)

  const { result } = renderHook(() => useProgressSocket())
  const socket = FakeWebSocket.instances[0]

  act(() => {
    socket.onmessage?.({ data: 'not json' })
    socket.onmessage?.({ data: JSON.stringify({ type: 'something-else' }) })
    socket.onmessage?.({
      data: JSON.stringify({ type: 'progress', item_id: 'item-1', downloaded_bytes: 42 }),
    })
  })

  expect(result.current.progressByItemId['item-1']).toBe(42)
})

test('reconnects after the server drops the connection', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)

  renderHook(() => useProgressSocket())
  expect(FakeWebSocket.instances).toHaveLength(1)

  // A backend restart (deploy, crash-recovery) closes every socket. Without a
  // reconnect the UI would keep rendering frozen progress forever.
  act(() => {
    FakeWebSocket.instances[0].onclose?.({ code: 1006 })
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })

  expect(FakeWebSocket.instances.length).toBeGreaterThan(1)
})

test('stops reconnecting when the server rejects the owner token', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)

  renderHook(() => useProgressSocket())

  // 4401 es el cierre del backend ante un token de dueño inválido. Reintentar
  // con el mismo token fallaría igual.
  act(() => {
    FakeWebSocket.instances[0].onclose?.({ code: 4401 })
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30000)
  })

  expect(FakeWebSocket.instances).toHaveLength(1)
})

test('does not reconnect after unmount', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)

  const { unmount } = renderHook(() => useProgressSocket())
  const socket = FakeWebSocket.instances[0]

  unmount()
  act(() => {
    socket.onclose?.({ code: 1006 })
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30000)
  })

  expect(FakeWebSocket.instances).toHaveLength(1)
})
