import { useCallback, useEffect, useRef, useState } from 'react'
import type { Snapshot, WsMessage } from '../types'

const WS_URL = '/ws'
const RECONNECT_DELAY_MS = 2000
const MAX_RECONNECT_DELAY_MS = 30_000

interface UseWebSocketReturn {
  snapshot: Snapshot | null
  connected: boolean
  lastMessageAt: number
}

export function useWebSocket(): UseWebSocketReturn {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastMessageAt, setLastMessageAt] = useState(0)

  const wsRef = useRef<WebSocket | null>(null)
  const delayRef = useRef(RECONNECT_DELAY_MS)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // A single shared "mounted" boolean lets a stale socket's onclose pass the
  // guard the moment a *newer* socket mounts (StrictMode double-invokes the
  // effect: mount -> cleanup -> mount again). The stale onclose would then
  // null out wsRef (clobbering the live socket) and schedule a spurious
  // reconnect. A per-connection generation token fixes this: each connect()
  // call only reacts to callbacks from its own generation.
  const generationRef = useRef(0)

  const connect = useCallback(() => {
    const myGeneration = ++generationRef.current
    const isCurrent = () => generationRef.current === myGeneration

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}${WS_URL}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!isCurrent()) return
      setConnected(true)
      delayRef.current = RECONNECT_DELAY_MS
    }

    ws.onmessage = (evt) => {
      if (!isCurrent()) return
      try {
        const msg: WsMessage = JSON.parse(evt.data)
        if (msg.type === 'snapshot') {
          setSnapshot(msg.data as Snapshot)
          setLastMessageAt(Date.now())
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      if (!isCurrent()) return
      setConnected(false)
      wsRef.current = null
      timerRef.current = setTimeout(() => {
        delayRef.current = Math.min(delayRef.current * 1.5, MAX_RECONNECT_DELAY_MS)
        connect()
      }, delayRef.current)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [])

  useEffect(() => {
    connect()
    // Keep-alive ping every 20s
    const ping = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping')
      }
    }, 20_000)
    return () => {
      generationRef.current++ // invalidate this connection's callbacks
      clearInterval(ping)
      if (timerRef.current) clearTimeout(timerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [connect])

  return { snapshot, connected, lastMessageAt }
}
