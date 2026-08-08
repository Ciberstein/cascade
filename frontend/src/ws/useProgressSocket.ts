import { useEffect, useRef, useState } from 'react'

interface ProgressMessage {
  type: 'progress'
  item_id: string
  downloaded_bytes: number
}

/** The backend's close code for a missing or expired session cookie. */
const UNAUTHORIZED_CLOSE_CODE = 4401

const RECONNECT_DELAY_MS = 2000

/**
 * Subscribes to the backend's throttled per-item progress feed.
 *
 * Downloads here run for hours, so the socket has to outlive the blips that
 * happen over that window: any close reconnects after a short delay. The one
 * exception is a rejected session, which can only fail the same way on retry -
 * that surfaces as `unauthorized` so the shell can send the user to login.
 */
export function useProgressSocket() {
  const [progressByItemId, setProgressByItemId] = useState<Record<string, number>>({})
  const [unauthorized, setUnauthorized] = useState(false)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    // Guards the async reconnect: without it, a socket that closes as the
    // component unmounts would still schedule a timer that opens a new one
    // nobody is listening to.
    let disposed = false
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const socket = new WebSocket(`${protocol}://${window.location.host}/ws`)
      socketRef.current = socket

      socket.onmessage = (event) => {
        const message = parseProgress(event.data)
        if (message) {
          setProgressByItemId((prev) => ({ ...prev, [message.item_id]: message.downloaded_bytes }))
        }
      }

      socket.onclose = (event) => {
        if (disposed) return
        if (event.code === UNAUTHORIZED_CLOSE_CODE) {
          setUnauthorized(true)
          return
        }
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }

    connect()

    return () => {
      disposed = true
      clearTimeout(reconnectTimer)
      socketRef.current?.close()
    }
  }, [])

  return { progressByItemId, unauthorized }
}

/**
 * Returns null for anything that isn't a well-formed progress frame. A single
 * bad frame must not throw out of onmessage - that would leave the socket open
 * but the UI stuck, which is harder to notice than dropped data.
 */
function parseProgress(data: unknown): ProgressMessage | null {
  if (typeof data !== 'string') return null
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') return null

  const message = parsed as Partial<ProgressMessage>
  if (
    message.type !== 'progress' ||
    typeof message.item_id !== 'string' ||
    typeof message.downloaded_bytes !== 'number'
  ) {
    return null
  }
  return message as ProgressMessage
}
