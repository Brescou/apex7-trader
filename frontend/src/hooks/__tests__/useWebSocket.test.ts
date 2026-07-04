import { StrictMode } from 'react'
import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWebSocket } from '../useWebSocket'

/** Minimal WebSocket stand-in. close() does NOT fire onclose synchronously —
 * a real browser socket's close completes asynchronously, which is exactly
 * what let a stale generation's onclose land after a newer one had already
 * taken over.
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  onopen: (() => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  readyState = 0

  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }
  close() {
    /* deferred on purpose — see comment above */
  }
  send() {}
}

describe('useWebSocket — stale-generation guard (StrictMode double-invoke)', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('creates exactly 2 sockets under StrictMode, and a late close from the first does not spawn a 3rd', () => {
    vi.useFakeTimers()
    try {
      renderHook(() => useWebSocket(), { wrapper: StrictMode })

      // React 18 StrictMode mounts, cleans up, and mounts again synchronously
      // in dev — exercising the exact mount -> cleanup -> mount sequence that
      // exposed the bug.
      expect(FakeWebSocket.instances).toHaveLength(2)
      const [ws1] = FakeWebSocket.instances

      // ws1's close (invoked during the StrictMode cleanup) resolves late,
      // after ws2 is already the live connection.
      ws1.onclose?.()

      // The reconnect the old code scheduled here runs on a setTimeout —
      // advance past it to prove none was actually queued.
      vi.advanceTimersByTime(5_000)

      // Before the generation-token fix, this stale onclose would null out
      // wsRef (clobbering ws2's reference) and schedule a reconnect — a 3rd
      // socket. It must now be a no-op.
      expect(FakeWebSocket.instances).toHaveLength(2)
    } finally {
      vi.useRealTimers()
    }
  })
})
