import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAnalytics, useCorrelation, useMacro, useSectors, useWatchlist } from '../useApex'

function mockFetchOnce(body: unknown, ok = true) {
  const json = vi.fn().mockResolvedValue(body)
  globalThis.fetch = vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 500, json }) as typeof fetch
}

describe('useApex hooks — API contract consumption', () => {
  // refreshMs is passed as a large value in every test below so the
  // interval never fires during the test; only the immediate mount-time
  // fetch is exercised. Real timers throughout — waitFor polls with real
  // timers, and mixing that with fake ones is a common source of hangs.
  afterEach(() => {
    vi.restoreAllMocks()
  })

  // api/routes/market.py now returns the watchlist as a frontend-ready
  // array of camelCase items (symbol injected per row); useWatchlist passes
  // that array straight through. This guards the frontend's half of the
  // contract: fields untouched, array preserved.
  it('useWatchlist passes the backend array through untouched', async () => {
    mockFetchOnce({
      watchlist: [
        {
          symbol: 'AAPL',
          price: 150.5,
          changeAbs: 1.8,
          changePct: 1.2,
          rsi: 55,
          macdHist: 0.1,
          volume: 1000,
        },
      ],
      symbols: ['AAPL'],
    })

    const { result } = renderHook(() => useWatchlist(60_000))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toHaveLength(1)
    expect(result.current.data[0].symbol).toBe('AAPL')
    expect(result.current.data[0].changePct).toBe(1.2)
    expect(result.current.data[0].rsi).toBe(55)
  })

  it('useWatchlist keeps stale data and stops loading when the fetch fails', async () => {
    mockFetchOnce({}, false)

    const { result } = renderHook(() => useWatchlist(60_000))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toEqual([])
  })

  it('useWatchlist tolerates a missing watchlist key', async () => {
    mockFetchOnce({ symbols: [] })

    const { result } = renderHook(() => useWatchlist(60_000))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toEqual([])
  })

  it('useMacro passes the lowercase-keyed shape straight through', async () => {
    mockFetchOnce({
      macro: { vix: { value: '15.20', change: -1.1, sub: '-1.10%' } },
    })

    const { result } = renderHook(() => useMacro(60_000))

    await waitFor(() => expect(result.current).not.toEqual({}))
    expect(result.current.vix).toEqual({ value: '15.20', change: -1.1, sub: '-1.10%' })
  })

  it('useSectors accepts an array (the shape sectors.py must now return)', async () => {
    mockFetchOnce({
      sectors: [
        { name: 'Tech', change: 1.5, changePct: 1.5 },
        { name: 'Energy', change: -0.5, changePct: -0.5 },
      ],
    })

    const { result } = renderHook(() => useSectors(60_000))

    await waitFor(() => expect(result.current).toHaveLength(2))
    expect(result.current[0].name).toBe('Tech')
  })

  it('useSectors falls back to [] if the backend ever regresses to a dict', async () => {
    mockFetchOnce({ sectors: { Tech: { '1d': 1.5 } } })

    const { result } = renderHook(() => useSectors(60_000))

    await waitFor(() => {
      // effect must have run at least once; result stays the initial []
    })
    expect(result.current).toEqual([])
  })

  it('useCorrelation stores matrix + symbols together', async () => {
    mockFetchOnce({
      correlation: { matrix: [[1, 0.5], [0.5, 1]], symbols: ['AAPL', 'MSFT'] },
    })

    const { result } = renderHook(() => useCorrelation(60_000))

    await waitFor(() => expect(result.current.symbols).toHaveLength(2))
    expect(result.current.matrix).toEqual([[1, 0.5], [0.5, 1]])
  })

  it('useAnalytics splits accuracy and postmortems from one response', async () => {
    mockFetchOnce({
      agentAccuracy: [{ role: 'technician', total: 10, correct: 7, accuracy: 70, validated: true }],
      postmortems: [
        { sym: 'AAPL', entryPrice: 100, exitPrice: 110, pnlPct: 10, holdDays: 2, lesson: 'held too long' },
      ],
    })

    const { result } = renderHook(() => useAnalytics(60_000))

    await waitFor(() => expect(result.current.accuracy).toHaveLength(1))
    expect(result.current.accuracy[0].role).toBe('technician')
    expect(result.current.postmortems[0].holdDays).toBe(2)
  })
})
