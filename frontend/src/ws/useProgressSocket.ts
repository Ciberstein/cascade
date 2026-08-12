import { useEffect, useRef, useState } from 'react'
import { ownerToken } from '../api/owner'

interface ProgressMessage {
  type: 'progress'
  item_id: string
  downloaded_bytes: number
}

/** The backend's close code when the owner token is missing or invalid. */
const INVALID_OWNER_CLOSE_CODE = 4401

const RECONNECT_DELAY_MS = 2000

/**
 * Subscribes to the backend's throttled per-item progress feed.
 *
 * Downloads here run for hours, so the socket has to outlive the blips that
 * happen over that window: any close reconnects after a short delay. The one
 * exception is a rejected owner token, which can only fail the same way on
 * retry.
 */
export function useProgressSocket() {
  const [progressByItemId, setProgressByItemId] = useState<Record<string, number>>({})
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    // Guards the async reconnect: without it, a socket that closes as the
    // component unmounts would still schedule a timer that opens a new one
    // nobody is listening to.
    let disposed = false
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      // The token travels in the query string: the browser's WebSocket API
      // cannot send headers of its own during the handshake.
      const socket = new WebSocket(
        `${protocol}://${window.location.host}/ws?owner=${encodeURIComponent(ownerToken())}`,
      )
      socketRef.current = socket

      socket.onmessage = (event) => {
        const message = parseProgress(event.data)
        if (message) {
          setProgressByItemId((prev) => ({ ...prev, [message.item_id]: message.downloaded_bytes }))
        }
      }

      socket.onclose = (event) => {
        if (disposed) return
        if (event.code === INVALID_OWNER_CLOSE_CODE) {
          // Retrying with the same token would fail the same way; the error
          // stays visible in the console and the rest of the app keeps polling.
          console.error("the server rejected this browser's identifier")
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

  return { progressByItemId }
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
