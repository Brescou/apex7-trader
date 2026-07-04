import { useCallback, useEffect, useState } from 'react'
import type { AgentAccuracy, EquityPoint, Postmortem, SectorItem, WatchlistItem } from '../types'

const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

async function post(path: string, body: unknown): Promise<unknown> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return r.json()
}

// ── Mode ──────────────────────────────────────────────────────────────────────
export function useSetMode() {
  return useCallback(async (mode: string) => {
    await post('/control/mode', { mode })
  }, [])
}

// ── Watchlist prices ──────────────────────────────────────────────────────────
export function useWatchlist(refreshMs = 10_000) {
  const [data, setData] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const res = await get<{ watchlist: Record<string, WatchlistItem> }>('/market/watchlist')
      const items = Object.values(res.watchlist || {})
      setData(items)
    } catch {
      // keep stale data
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, refreshMs)
    return () => clearInterval(t)
  }, [refresh, refreshMs])

  return { data, loading, refresh }
}

// ── Macro ─────────────────────────────────────────────────────────────────────
export function useMacro(refreshMs = 60_000) {
  const [data, setData] = useState<Record<string, unknown>>({})

  useEffect(() => {
    const refresh = async () => {
      try {
        const res = await get<{ macro: Record<string, unknown> }>('/market/macro')
        setData(res.macro || {})
      } catch { /* keep stale */ }
    }
    refresh()
    const t = setInterval(refresh, refreshMs)
    return () => clearInterval(t)
  }, [refreshMs])

  return data
}

// ── Sectors ───────────────────────────────────────────────────────────────────
export function useSectors(refreshMs = 60_000) {
  const [data, setData] = useState<SectorItem[]>([])

  useEffect(() => {
    const refresh = async () => {
      try {
        const res = await get<{ sectors: SectorItem[] }>('/market/sectors')
        setData(Array.isArray(res.sectors) ? res.sectors : [])
      } catch { /* keep stale */ }
    }
    refresh()
    const t = setInterval(refresh, refreshMs)
    return () => clearInterval(t)
  }, [refreshMs])

  return data
}

// ── Symbol sparkline (1-day hourly OHLC) ───────────────────────────────────────
export function useSparkline(symbol: string | null, refreshMs = 60_000) {
  const [data, setData] = useState<EquityPoint[]>([])

  useEffect(() => {
    if (!symbol) {
      setData([])
      return
    }
    let cancelled = false
    const refresh = async () => {
      try {
        const res = await get<{ sparkline: EquityPoint[] }>(`/market/sparkline/${symbol}`)
        if (!cancelled) setData(Array.isArray(res.sparkline) ? res.sparkline : [])
      } catch { /* keep stale */ }
    }
    refresh()
    const t = setInterval(refresh, refreshMs)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [symbol, refreshMs])

  return data
}

// ── Correlation ───────────────────────────────────────────────────────────────
export function useCorrelation(refreshMs = 120_000) {
  const [data, setData] = useState<{ matrix: number[][], symbols: string[] }>({ matrix: [], symbols: [] })

  useEffect(() => {
    const refresh = async () => {
      try {
        const res = await get<{ correlation: { matrix: number[][], symbols: string[] } }>('/market/correlation')
        if (res.correlation) setData(res.correlation)
      } catch { /* keep stale */ }
    }
    refresh()
    const t = setInterval(refresh, refreshMs)
    return () => clearInterval(t)
  }, [refreshMs])

  return data
}

// ── Analytics ─────────────────────────────────────────────────────────────────
export function useAnalytics(refreshMs = 30_000) {
  const [accuracy, setAccuracy] = useState<AgentAccuracy[]>([])
  const [postmortems, setPostmortems] = useState<Postmortem[]>([])

  useEffect(() => {
    const refresh = async () => {
      try {
        const res = await get<{ agentAccuracy: AgentAccuracy[]; postmortems: Postmortem[] }>('/analytics')
        setAccuracy(res.agentAccuracy || [])
        setPostmortems(res.postmortems || [])
      } catch { /* keep stale */ }
    }
    refresh()
    const t = setInterval(refresh, refreshMs)
    return () => clearInterval(t)
  }, [refreshMs])

  return { accuracy, postmortems }
}
