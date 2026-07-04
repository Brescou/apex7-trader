import { useState } from 'react'
import { useMacro, useWatchlist, useSectors, useCorrelation, useSparkline } from '../../hooks/useApex'
import { EquityChart } from '../live/EquityChart'
import styles from './TerminalTab.module.css'

function pct(n: number) { return (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%' }
function cls(n: number) { return n >= 0 ? 'pos' : 'neg' }

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

const MACRO_LABELS: Record<string, string> = {
  vix: 'VIX', spy: 'SPY', dxy: 'DXY',
  fear_greed: 'FEAR / GREED', fed_funds: 'FED FUNDS', ten_year: '10Y YIELD',
}

export function TerminalTab() {
  const macroRaw = useMacro()
  const { data: wl } = useWatchlist()
  const sectors = useSectors()
  const { matrix: corrMatrix, symbols: corrSyms } = useCorrelation()
  const [selectedSym, setSelectedSym] = useState<string | null>(null)

  // Build macro display list from whatever keys the backend returns
  const macroEntries = Object.entries(macroRaw).slice(0, 6).map(([k, v]) => ({
    name: MACRO_LABELS[k] ?? k.toUpperCase(),
    val: String((v as Record<string,unknown>)?.value ?? v ?? '—'),
    sub: String((v as Record<string,unknown>)?.change ?? (v as Record<string,unknown>)?.sub ?? ''),
    subCls: Number((v as Record<string,unknown>)?.change ?? 0) >= 0 ? 'pos' : 'neg',
  }))

  const selected = wl.find(w => w.symbol === selectedSym) ?? wl[0]
  const sparkline = useSparkline(selected?.symbol ?? null)

  return (
    <div className={styles.term}>
      {/* Macro bar */}
      <div className={styles.macro}>
        {macroEntries.length > 0 ? macroEntries.map((m, i) => (
          <div key={i} className={styles.mbloc}>
            <span className={styles.mname}>{m.name}</span>
            <span className={`mono ${styles.mbig}`}>{m.val}</span>
            <span className={`mono ${styles.msub} ${m.subCls}`}>{m.sub}</span>
          </div>
        )) : ['VIX','SPY','DXY','FEAR / GREED','FED FUNDS','10Y YIELD'].map(n => (
          <div key={n} className={styles.mbloc}>
            <span className={styles.mname}>{n}</span>
            <span className={`mono ${styles.mbig} t-faint`}>—</span>
          </div>
        ))}
      </div>

      {/* Grid */}
      <div className={styles.grid}>
        {/* Watchlist */}
        <div className={styles.col}>
          <div className={styles.colHd}>
            <span className="pip" style={{ background: 'var(--blue)' }} />
            <span className="seclbl">Watchlist</span>
            <span className="mono t-faint" style={{ fontSize: '8.5px', marginLeft: 'auto' }}>{wl.length}/20</span>
          </div>
          {wl.map(w => (
            <div
              key={w.symbol}
              className={`${styles.wrow} ${selectedSym === w.symbol ? styles.wsel : ''}`}
              onClick={() => setSelectedSym(w.symbol)}
            >
              <span className={styles.wsym}>{w.symbol}</span>
              <span className={`mono ${styles.wpx}`}>{Number(w.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              <span className={`mono ${styles.wchg} ${cls(w.changePct ?? w.change ?? 0)}`}>{pct(w.changePct ?? w.change ?? 0)}</span>
              {w.rsi != null && <span className={`mono ${styles.wrsi} ${w.rsi <= 35 ? 'pos' : w.rsi >= 65 ? 'neg' : 't-dim'}`}>RSI {Math.round(w.rsi)}</span>}
            </div>
          ))}
        </div>

        {/* Symbol detail */}
        <div className={styles.col}>
          {selected && <>
            <div className={styles.symHd}>
              <div>
                <div className="flex items-center gap-2">
                  <span className={styles.bigsym}>{selected.symbol}</span>
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className={`mono ${styles.bigpx}`}>{Number(selected.price).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
                <div className={`mono ${cls(selected.changePct ?? 0)}`} style={{ fontSize: 12, fontWeight: 600, marginTop: 3 }}>{pct(selected.changePct ?? selected.change ?? 0)}</div>
              </div>
            </div>
            <div className={styles.chartWrap}>
              {sparkline.length > 0
                ? <EquityChart points={sparkline} height={190} color="var(--blue)" />
                : <span className="t-faint seclbl">Loading chart…</span>}
            </div>
          </>}
        </div>

        {/* Sectors + correlation */}
        <div className={`${styles.col} ${styles.colLast}`}>
          <div className={styles.colHd}>
            <span className="pip" style={{ background: 'var(--orange)' }} />
            <span className="seclbl">Sector Rotation</span>
          </div>
          <div className={styles.heat}>
            {sectors.length > 0 ? sectors.slice(0, 10).map((s, i) => {
              const v = Number(s.changePct ?? s.change ?? 0)
              return (
                <div key={i} className={`${styles.hcell} ${styles[heatClass(v)]}`}>
                  <span className={styles.hname}>{s.name}</span>
                  <span className={`mono ${styles.hval} ${cls(v)}`}>{pct(v)}</span>
                </div>
              )
            }) : <span className="t-faint seclbl">Loading…</span>}
          </div>

          {corrMatrix.length > 0 && <>
            <div className={styles.colHd} style={{ marginTop: 18 }}>
              <span className="pip" style={{ background: 'var(--purple)' }} />
              <span className="seclbl">Correlation · 30D</span>
            </div>
            <div className={styles.corr} style={{ gridTemplateColumns: `auto repeat(${corrSyms.length}, 1fr)` }}>
              <div />
              {corrSyms.map(s => <div key={s} className={styles.chead}>{s}</div>)}
              {corrMatrix.map((row, ri) => <>
                <div key={`lbl-${ri}`} className={styles.chead}>{corrSyms[ri]}</div>
                {row.map((v, ci) => (
                  <div key={ci} className={`${styles.ccell} ${corrClass(v)}`}>{v.toFixed(2)}</div>
                ))}
              </>)}
            </div>
          </>}
        </div>
      </div>
    </div>
  )
}
