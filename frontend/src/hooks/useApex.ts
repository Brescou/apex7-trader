import { useCallback, useEffect, useRef, useState } from 'react'
import type { AgentAccuracy, CalendarEvent, EquityPoint, Fundamentals, NewsItem, OhlcvBar, Postmortem, SectorItem, WatchlistItem } from '../types'

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

// ── Live clock (ticks every second) ─────────────────────────────────────────
export function useClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

// ── Mode ──────────────────────────────────────────────────────────────────────
export function useSetMode() {
  return useCallback(async (mode: string) => {
    await post('/control/mode', { mode })
  }, [])
}

// ── Watchlist mutations ───────────────────────────────────────────────────────
export function useWatchlistMutations() {
  const add = useCallback(async (symbol: string) => {
    const res = await post('/control/watchlist/add', { symbol }) as { ok?: boolean }
    return Boolean(res?.ok)
  }, [])
  const remove = useCallback(async (symbol: string) => {
    const res = await post('/control/watchlist/remove', { symbol }) as { ok?: boolean }
    return Boolean(res?.ok)
  }, [])
  return { add, remove }
}

// ── Watchlist prices ──────────────────────────────────────────────────────────
export function useWatchlist(refreshMs = 10_000) {
  const [data, setData] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const res = await get<{ watchlist: WatchlistItem[] }>('/market/watchlist')
      setData(Array.isArray(res.watchlist) ? res.watchlist : [])
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

// ── Chart (OHLCV bars) ────────────────────────────────────────────────────────
export function useChart(symbol: string | null, period = '1mo') {
  const [bars, setBars] = useState<OhlcvBar[]>([])
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!symbol) { setBars([]); return }
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    fetch(`/api/market/chart/${encodeURIComponent(symbol)}?period=${period}`, { signal: ctrl.signal })
      .then(r => r.json())
      .then(data => { setBars(data.bars ?? []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [symbol, period])

  return { bars, loading }
}

// ── News ──────────────────────────────────────────────────────────────────────
export function useNews(symbol: string | null) {
  const [news, setNews] = useState<NewsItem[]>([])

  useEffect(() => {
    if (!symbol) { setNews([]); return }
    fetch(`/api/market/news/${encodeURIComponent(symbol)}`)
      .then(r => r.json())
      .then(data => setNews(data.news ?? []))
      .catch(() => { /* keep stale */ })
  }, [symbol])

  return news
}

// ── Fundamentals ──────────────────────────────────────────────────────────────
export function useFundamentals(symbol: string | null) {
  const [data, setData] = useState<Fundamentals>({})

  useEffect(() => {
    if (!symbol) { setData({}); return }
    fetch(`/api/market/fundamentals/${encodeURIComponent(symbol)}`)
      .then(r => r.json())
      .then(res => setData(res.fundamentals ?? {}))
      .catch(() => { /* keep stale */ })
  }, [symbol])

  return data
}

// ── Economic calendar ─────────────────────────────────────────────────────────
export function useCalendar(refreshMs = 300_000) {
  const [events, setEvents] = useState<CalendarEvent[]>([])

  useEffect(() => {
    const refresh = async () => {
      try {
        const res = await get<{ calendar: CalendarEvent[] }>('/market/calendar')
        setEvents(Array.isArray(res.calendar) ? res.calendar : [])
      } catch { /* keep stale */ }
    }
    refresh()
    const t = setInterval(refresh, refreshMs)
    return () => clearInterval(t)
  }, [refreshMs])

  return events
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
