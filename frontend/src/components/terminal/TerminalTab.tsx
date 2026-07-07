import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  useCalendar,
  useChart,
  useClock,
  useCorrelation,
  useFundamentals,
  useMacro,
  useNews,
  useSectors,
  useWatchlist,
  useWatchlistMutations,
} from '../../hooks/useApex'
import type { WatchlistItem } from '../../types'
import { CandleChart } from './CandleChart'
import { CommandBar } from './CommandBar'
import styles from './TerminalTab.module.css'

// ── helpers ───────────────────────────────────────────────────────────────────
function pct(n: number) { return (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%' }
function cls(n: number) { return n >= 0 ? 'pos' : 'neg' }
function fmt2(n: number) { return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtVol(v: number) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B'
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K'
  return String(v)
}
function fmtCap(v?: number) {
  if (!v) return '—'
  if (v >= 1e12) return '$' + (v / 1e12).toFixed(2) + 'T'
  if (v >= 1e9)  return '$' + (v / 1e9).toFixed(2) + 'B'
  if (v >= 1e6)  return '$' + (v / 1e6).toFixed(1) + 'M'
  return '$' + v.toFixed(0)
}

function heatClass(v: number) {
  const i = Math.min(3, Math.ceil(Math.abs(v) / 0.4))
  return v >= 0 ? `hp${i}` : `hn${i}`
}
function corrClass(v: number) {
  if (v >= 0.99) return styles.c4
  if (v >= 0.7)  return styles.c3
  if (v >= 0.4)  return styles.c2
  if (v >= 0)    return styles.c1
  return styles.c5
}

function marketStatus(now: Date): { label: string; open: boolean } {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', hour12: false, weekday: 'short', hour: 'numeric', minute: 'numeric',
  })
  const p = Object.fromEntries(fmt.formatToParts(now).map(x => [x.type, x.value])) as Record<string, string>
  const wd = p.weekday
  const hour = parseInt(p.hour === '24' ? '0' : p.hour, 10)
  const min = parseInt(p.minute, 10)
  const mins = hour * 60 + min
  const weekday = !['Sat', 'Sun'].includes(wd)
  if (weekday && mins >= 570 && mins < 960) return { label: 'OPEN', open: true }
  if (weekday && mins >= 240 && mins < 570) return { label: 'PRE-MKT', open: false }
  if (weekday && mins >= 960 && mins < 1200) return { label: 'AFTER-HRS', open: false }
  return { label: 'CLOSED', open: false }
}

const MACRO_LABELS: Record<string, string> = {
  vix: 'VIX', spy: 'SPY', dxy: 'DXY',
  fear_greed: 'F&G', fed_funds: 'FED', ten_year: '10Y',
}
const PERIODS = ['1d', '5d', '1mo', '3mo', '6mo', '1y'] as const
type Period = typeof PERIODS[number]
type SortKey = 'symbol' | 'price' | 'changePct' | 'rsi'
type Tab = 'overview' | 'news' | 'financials'

const LEFT_MIN = 190, LEFT_MAX = 460
const RIGHT_MIN = 230, RIGHT_MAX = 540

// ── RangeBar: position of price within [lo, hi] ──────────────────────────────
function RangeBar({ lo, hi, price, loLabel, hiLabel }: { lo?: number; hi?: number; price: number; loLabel?: string; hiLabel?: string }) {
  if (lo == null || hi == null || hi <= lo) return null
  const posPct = Math.max(0, Math.min(100, ((price - lo) / (hi - lo)) * 100))
  return (
    <div className={styles.rng}>
      <span className={`mono ${styles.rngLbl}`}>{loLabel ?? fmt2(lo)}</span>
      <div className={styles.rngTrack}>
        <div className={styles.rngMark} style={{ left: posPct + '%' }} />
      </div>
      <span className={`mono ${styles.rngLbl}`}>{hiLabel ?? fmt2(hi)}</span>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────
export function TerminalTab() {
  const macroRaw     = useMacro()
  const { data: wl, refresh: refreshWl } = useWatchlist()
  const sectors      = useSectors()
  const { matrix: corrMatrix, symbols: corrSyms } = useCorrelation()
  const calendar     = useCalendar()
  const { add, remove } = useWatchlistMutations()
  const now          = useClock()

  const [selectedSym, setSelectedSym] = useState<string | null>(null)
  const [period, setPeriod] = useState<Period>('3mo')
  const [tab, setTab] = useState<Tab>('overview')
  const [addInput, setAddInput] = useState('')
  const [adding, setAdding] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('symbol')
  const [sortDir, setSortDir] = useState<1 | -1>(1)

  const activeSym = selectedSym ?? wl[0]?.symbol ?? null
  const { bars }     = useChart(activeSym, period)
  const news         = useNews(activeSym)
  const fundamentals = useFundamentals(activeSym)
  const selected     = wl.find(w => w.symbol === activeSym)
  const symbols      = useMemo(() => wl.map(w => w.symbol), [wl])

  // ── Resizable columns ──────────────────────────────────────────────────────
  const [leftW, setLeftW] = useState(240)
  const [rightW, setRightW] = useState(300)
  const dragRef = useRef<{ side: 'left' | 'right'; startX: number; startW: number } | null>(null)
  const onDragMove = useCallback((e: MouseEvent) => {
    const d = dragRef.current
    if (!d) return
    const dx = e.clientX - d.startX
    if (d.side === 'left') setLeftW(Math.max(LEFT_MIN, Math.min(LEFT_MAX, d.startW + dx)))
    else setRightW(Math.max(RIGHT_MIN, Math.min(RIGHT_MAX, d.startW - dx)))
  }, [])
  const onDragEnd = useCallback(() => {
    dragRef.current = null
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    window.removeEventListener('mousemove', onDragMove)
    window.removeEventListener('mouseup', onDragEnd)
  }, [onDragMove])
  const startDrag = useCallback((side: 'left' | 'right') => (e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { side, startX: e.clientX, startW: side === 'left' ? leftW : rightW }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('mousemove', onDragMove)
    window.addEventListener('mouseup', onDragEnd)
  }, [leftW, rightW, onDragMove, onDragEnd])
  useEffect(() => () => onDragEnd(), [onDragEnd])

  // ── Price flash ────────────────────────────────────────────────────────────
  const prevPrices = useRef<Record<string, number>>({})
  const [flashMap, setFlashMap] = useState<Record<string, 'up' | 'down'>>({})
  useEffect(() => {
    const next: Record<string, 'up' | 'down'> = {}
    for (const w of wl) {
      const prev = prevPrices.current[w.symbol]
      if (prev != null && w.price !== prev) next[w.symbol] = w.price > prev ? 'up' : 'down'
      prevPrices.current[w.symbol] = w.price
    }
    if (Object.keys(next).length) {
      setFlashMap(next)
      const t = setTimeout(() => setFlashMap({}), 650)
      return () => clearTimeout(t)
    }
  }, [wl])

  // ── Sorted watchlist ───────────────────────────────────────────────────────
  const sortedWl = useMemo(() => {
    const arr = [...wl]
    arr.sort((a, b) => {
      let av: number | string, bv: number | string
      if (sortKey === 'symbol') { av = a.symbol; bv = b.symbol }
      else if (sortKey === 'changePct') { av = a.changePct ?? 0; bv = b.changePct ?? 0 }
      else if (sortKey === 'rsi') { av = a.rsi ?? 0; bv = b.rsi ?? 0 }
      else { av = a.price ?? 0; bv = b.price ?? 0 }
      if (av < bv) return -1 * sortDir
      if (av > bv) return 1 * sortDir
      return 0
    })
    return arr
  }, [wl, sortKey, sortDir])

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir(d => (d === 1 ? -1 : 1))
    else { setSortKey(k); setSortDir(k === 'symbol' ? 1 : -1) }
  }
  const sortArrow = (k: SortKey) => (sortKey === k ? (sortDir === 1 ? '▲' : '▼') : '')

  // ── Add / remove ───────────────────────────────────────────────────────────
  const handleAdd = useCallback(async (rawSym?: string) => {
    const sym = (rawSym ?? addInput).trim().toUpperCase()
    if (!sym) return false
    setAdding(true)
    const ok = await add(sym)
    setAdding(false)
    if (ok) { setAddInput(''); refreshWl(); setSelectedSym(sym) }
    return ok
  }, [addInput, add, refreshWl])

  const handleRemove = useCallback(async (sym: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const ok = await remove(sym)
    if (ok) { if (activeSym === sym) setSelectedSym(null); refreshWl() }
  }, [remove, activeSym, refreshWl])

  // ── Macro entries ──────────────────────────────────────────────────────────
  const macroEntries = Object.entries(macroRaw).slice(0, 6).map(([k, v]) => {
    const obj = v as Record<string, unknown>
    return {
      name: MACRO_LABELS[k] ?? k.toUpperCase(),
      val:  String(obj?.value ?? v ?? '—'),
      sub:  String(obj?.change ?? obj?.sub ?? ''),
      subCls: Number(obj?.change ?? 0) >= 0 ? 'pos' : 'neg',
    }
  })
  const placeholderMacro = ['VIX', 'SPY', 'DXY', 'F&G', 'FED', '10Y']
  const mkt = marketStatus(now)
  const etTime = now.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false })

  // ── Fundamentals strip / stats ─────────────────────────────────────────────
  const fnd = fundamentals
  const stat = (label: string, val: string) => ({ label, val })
  const stats = [
    stat('Name', fnd.name ?? '—'),
    stat('Sector', fnd.sector ?? '—'),
    stat('Industry', fnd.industry ?? '—'),
    stat('Market Cap', fmtCap(fnd.marketCap)),
    stat('P/E (TTM)', fnd.peRatio ? Number(fnd.peRatio).toFixed(2) : '—'),
    stat('Forward P/E', fnd.forwardPe ? Number(fnd.forwardPe).toFixed(2) : '—'),
    stat('EPS', fnd.eps ? Number(fnd.eps).toFixed(2) : '—'),
    stat('Dividend Yield', fnd.dividendYield ? (Number(fnd.dividendYield) * 100).toFixed(2) + '%' : '—'),
    stat('Beta', fnd.beta ? Number(fnd.beta).toFixed(2) : '—'),
    stat('52W High', fnd.high52w ? '$' + fmt2(Number(fnd.high52w)) : '—'),
    stat('52W Low', fnd.low52w ? '$' + fmt2(Number(fnd.low52w)) : '—'),
  ]
  const stripItems = [
    { lbl: 'P/E',   val: fnd.peRatio ? Number(fnd.peRatio).toFixed(1) : '—' },
    { lbl: 'FWD',   val: fnd.forwardPe ? Number(fnd.forwardPe).toFixed(1) : '—' },
    { lbl: 'MKCP',  val: fmtCap(fnd.marketCap) },
    { lbl: 'DIV%',  val: fnd.dividendYield ? (Number(fnd.dividendYield) * 100).toFixed(2) + '%' : '—' },
    { lbl: 'BETA',  val: fnd.beta ? Number(fnd.beta).toFixed(2) : '—' },
    { lbl: 'VOL',   val: selected ? fmtVol(Number(selected.volume || 0)) : '—' },
  ]

  return (
    <div className={styles.term}>
      {/* ── COMMAND BAR ───────────────────────────────────────────────────── */}
      <CommandBar symbols={symbols} onSelect={(s) => { setSelectedSym(s); setTab('overview') }} onAdd={(s) => handleAdd(s)} />

      {/* ── MACRO BAR ─────────────────────────────────────────────────────── */}
      <div className={styles.macro}>
        <div className={`${styles.mbloc} ${styles.mktBloc}`}>
          <span className={styles.mname}>MARKET</span>
          <span className={`${styles.mktPill} ${mkt.open ? styles.mktOpen : styles.mktClosed}`}>
            <span className={styles.mktDot} /> {mkt.label}
          </span>
          <span className={`mono ${styles.clock}`}>{etTime} ET</span>
        </div>
        {(macroEntries.length > 0 ? macroEntries : placeholderMacro.map(n => ({ name: n, val: '—', sub: '', subCls: 'neg' }))).map((m, i) => (
          <div key={i} className={styles.mbloc}>
            <span className={styles.mname}>{m.name}</span>
            <span className={`mono ${styles.mbig} ${m.val === '—' ? 't-faint' : ''}`}>{m.val}</span>
            {m.sub && <span className={`mono ${styles.msub} ${m.subCls}`}>{m.sub}</span>}
          </div>
        ))}
      </div>

      {/* ── BODY ──────────────────────────────────────────────────────────── */}
      <div className={styles.body}>

        {/* ── COL 1 : WATCHLIST ─────────────────────────────────────────── */}
        <div className={styles.col} style={{ width: leftW, flex: `0 0 ${leftW}px` }}>
          <div className={styles.colHd}>
            <span className="pip" style={{ background: 'var(--blue)' }} />
            <span className="seclbl">Watchlist</span>
            <span className="mono t-faint" style={{ fontSize: '8.5px', marginLeft: 'auto' }}>{wl.length}/20</span>
          </div>

          <div className={styles.addRow}>
            <input
              className={styles.addInput}
              value={addInput}
              placeholder="ADD TICKER…"
              maxLength={6}
              onChange={e => setAddInput(e.target.value.toUpperCase())}
              onKeyDown={e => { if (e.key === 'Enter') handleAdd() }}
            />
            <button className={styles.addBtn} onClick={() => handleAdd()} disabled={adding || !addInput.trim()}>
              {adding ? '…' : '+'}
            </button>
          </div>

          <div className={styles.whead}>
            <button className={styles.whBtn} onClick={() => toggleSort('symbol')}>SYM {sortArrow('symbol')}</button>
            <button className={styles.whBtn} onClick={() => toggleSort('price')}>PRICE {sortArrow('price')}</button>
            <button className={styles.whBtn} onClick={() => toggleSort('changePct')}>CHG% {sortArrow('changePct')}</button>
            <button className={styles.whBtn} onClick={() => toggleSort('rsi')}>RSI {sortArrow('rsi')}</button>
          </div>

          {sortedWl.map((w: WatchlistItem) => {
            const chg = w.changePct ?? w.change ?? 0
            const rsi = w.rsi
            let rsiCls = 't-dim'
            if (rsi != null) rsiCls = rsi <= 35 ? 'pos' : rsi >= 65 ? 'neg' : 't-mid'
            const flash = flashMap[w.symbol]
            return (
              <div
                key={w.symbol}
                className={`${styles.wrow} ${activeSym === w.symbol ? styles.wsel : ''} ${flash === 'up' ? styles.flashUp : flash === 'down' ? styles.flashDown : ''}`}
                onClick={() => { setSelectedSym(w.symbol); setTab('overview') }}
              >
                <div className={styles.wmain}>
                  <span className={styles.wsym}>{w.symbol}</span>
                  <span className={`mono ${styles.wpx}`}>{fmt2(Number(w.price))}</span>
                  <span className={`mono ${styles.wchg} ${cls(chg)}`}>{pct(chg)}</span>
                  <span className={`mono ${styles.wrsi} ${rsiCls}`}>{rsi != null ? Math.round(rsi) : '—'}</span>
                </div>
                {w.low52w != null && w.high52w != null && (
                  <div className={styles.wrange}>
                    <div className={styles.wrangeFill} style={{ width: Math.max(0, Math.min(100, ((w.price - w.low52w) / (w.high52w - w.low52w)) * 100)) + '%' }} />
                  </div>
                )}
                <button className={styles.wrm} title="Remove" onClick={e => handleRemove(w.symbol, e)}>×</button>
              </div>
            )
          })}
        </div>

        <div className={styles.resizer} onMouseDown={startDrag('left')} />

        {/* ── COL 2 : SYMBOL PANEL ───────────────────────────────────────── */}
        <div className={`${styles.col} ${styles.colMid}`}>
          {selected ? (
            <>
              {/* header */}
              <div className={styles.symHd}>
                <div className={styles.symId}>
                  <span className={styles.bigsym}>{selected.symbol}</span>
                  <span className={styles.symName}>{fnd.name ?? '—'}</span>
                  {fnd.sector && <span className={styles.symSector}>{fnd.sector}</span>}
                </div>
                <div className={styles.symRight}>
                  <span className={`mono ${styles.bigpx}`}>${fmt2(Number(selected.price))}</span>
                  <span className={`mono ${styles.bigchg} ${cls(selected.changePct ?? 0)}`}>
                    {selected.changeAbs != null ? (selected.changeAbs >= 0 ? '+' : '') + fmt2(selected.changeAbs) + '  ' : ''}{pct(selected.changePct ?? selected.change ?? 0)}
                  </span>
                </div>
              </div>

              {/* day range bar */}
              <RangeBar lo={selected.dayLow} hi={selected.dayHigh} price={selected.price} />

              {/* tabs */}
              <div className={styles.tabs}>
                {(['overview', 'news', 'financials'] as Tab[]).map(t => (
                  <button key={t} className={`${styles.tabBtn} ${tab === t ? styles.tabActive : ''}`} onClick={() => setTab(t)}>
                    {t === 'overview' ? 'OVERVIEW' : t === 'news' ? `NEWS (${news.length})` : 'FINANCIALS'}
                  </button>
                ))}
              </div>

              {/* OVERVIEW */}
              {tab === 'overview' && (
                <>
                  <div className={styles.periods}>
                    {PERIODS.map(p => (
                      <button key={p} className={`${styles.pBtn} ${period === p ? styles.pBtnActive : ''}`} onClick={() => setPeriod(p)}>
                        {p.toUpperCase()}
                      </button>
                    ))}
                  </div>
                  <div className={styles.chartWrap}>
                    <CandleChart bars={bars} height={300} />
                  </div>
                  <div className={styles.fundStrip}>
                    {stripItems.map(f => (
                      <div key={f.lbl} className={styles.fundCell}>
                        <span className={styles.fundLbl}>{f.lbl}</span>
                        <span className={`mono ${styles.fundVal}`}>{f.val}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {/* NEWS */}
              {tab === 'news' && (
                <div className={styles.newsList}>
                  {news.length === 0 && <span className="t-faint seclbl" style={{ padding: '8px 0', display: 'block' }}>No news</span>}
                  {news.map((nn, i) => (
                    <a key={i} href={nn.link || '#'} target="_blank" rel="noreferrer" className={styles.newsItem}>
                      <div className={styles.newsTitle}>{nn.title}</div>
                      <div className={styles.newsMeta}>
                        <span className="mono t-faint">{nn.publisher}</span>
                        {nn.sentiment && <span className={`mono ${styles.sent} ${nn.sentiment === 'positive' ? 'pos' : nn.sentiment === 'negative' ? 'neg' : 't-faint'}`}>{nn.sentiment.toUpperCase()}</span>}
                        <span className="mono t-faint">{nn.time}</span>
                      </div>
                    </a>
                  ))}
                </div>
              )}

              {/* FINANCIALS */}
              {tab === 'financials' && (
                <div className={styles.statGrid}>
                  {stats.map(s => (
                    <div key={s.label} className={styles.statRow}>
                      <span className={styles.statLbl}>{s.label}</span>
                      <span className={`mono ${styles.statVal}`}>{s.val}</span>
                    </div>
                  ))}
                  <div className={styles.statRange}>
                    <span className={styles.statLbl}>52-Week Range</span>
                    <RangeBar lo={fnd.low52w} hi={fnd.high52w} price={selected.price}
                      loLabel={fnd.low52w ? '$' + fmt2(Number(fnd.low52w)) : ''} hiLabel={fnd.high52w ? '$' + fmt2(Number(fnd.high52w)) : ''} />
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className={styles.noSym}><span className="seclbl t-faint">Select a symbol — type a ticker in the command bar</span></div>
          )}
        </div>

        <div className={styles.resizer} onMouseDown={startDrag('right')} />

        {/* ── COL 3 : SECTOR + CORRELATION + CALENDAR ───────────────────── */}
        <div className={`${styles.col} ${styles.colLast}`} style={{ width: rightW, flex: `0 0 ${rightW}px` }}>
          <div className={styles.colHd}>
            <span className="pip" style={{ background: 'var(--orange)' }} />
            <span className="seclbl">Sector Rotation</span>
          </div>
          <div className={styles.heat}>
            {sectors.length > 0 ? sectors.slice(0, 10).map((s, i) => {
              const v = Number(s.changePct ?? s.change ?? 0)
              return (
                <div key={i} className={`${styles.hcell} ${styles[heatClass(v) as keyof typeof styles]}`}>
                  <span className={styles.hname}>{s.name}</span>
                  <span className={`mono ${styles.hval} ${cls(v)}`}>{pct(v)}</span>
                </div>
              )
            }) : <span className="t-faint seclbl">Loading…</span>}
          </div>

          {corrMatrix.length > 0 && (
            <>
              <div className={styles.colHd} style={{ marginTop: 18 }}>
                <span className="pip" style={{ background: 'var(--purple)' }} />
                <span className="seclbl">Correlation · 30D</span>
              </div>
              <div className={styles.corr} style={{ gridTemplateColumns: `auto repeat(${corrSyms.length}, 1fr)` }}>
                <div />
                {corrSyms.map(s => <div key={s} className={styles.chead}>{s}</div>)}
                {corrMatrix.map((row, ri) => (
                  <>
                    <div key={`lbl-${ri}`} className={styles.chead}>{corrSyms[ri]}</div>
                    {row.map((v, ci) => (
                      <div key={ci} className={`${styles.ccell} ${corrClass(v)}`}>{v.toFixed(2)}</div>
                    ))}
                  </>
                ))}
              </div>
            </>
          )}

          {calendar.length > 0 && (
            <>
              <div className={styles.colHd} style={{ marginTop: 18 }}>
                <span className="pip" style={{ background: 'var(--cyan)' }} />
                <span className="seclbl">Economic Calendar</span>
              </div>
              <div className={styles.calList}>
                {calendar.slice(0, 12).map((ev, i) => (
                  <div key={i} className={`${styles.calRow} ${ev.importance === 'high' ? styles.calHigh : ''}`}>
                    <div className={styles.calDate}>
                      <span className={`mono ${styles.calDays}`}>{ev.daysUntil === 0 ? 'TODAY' : `+${ev.daysUntil}d`}</span>
                      <span className="mono t-faint" style={{ fontSize: 9 }}>{ev.eventDate.slice(5)}</span>
                    </div>
                    <div className={styles.calInfo}>
                      <span className={styles.calEvt}>{ev.event}</span>
                      {ev.symbol && <span className={`mono ${styles.calSym}`}>{ev.symbol}</span>}
                    </div>
                    <div className={`${styles.calKind} ${ev.kind === 'earnings' ? styles.calEarnings : styles.calMacro}`}>
                      {ev.kind === 'earnings' ? 'EARN' : 'MACRO'}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
