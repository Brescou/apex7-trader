import { ScrollArea } from '@mantine/core'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Snapshot } from '../../types'
import { EquityChart } from './EquityChart'
import { ActivityLog } from './ActivityLog'
import styles from './LiveTab.module.css'

const SIDE_MIN = 210, SIDE_MAX = 460
const CHART_MIN = 120, CHART_MAX = 520

interface Props { snapshot: Snapshot | null }

function fmt(n: number) { return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function pct(n: number) { return (n >= 0 ? '+' : '') + n.toFixed(2) + '%' }
function cls(n: number) { return n >= 0 ? 'pos' : 'neg' }

const AGENT_META: Record<string, { color: string; label: string; model: string }> = {
  technician:    { color: '#5b9dff', label: 'TECHNICIAN',    model: 'HAIKU' },
  analyst:       { color: '#2dd4a0', label: 'ANALYST',       model: 'SONNET' },
  risk_manager:  { color: '#f0934d', label: 'RISK MANAGER',  model: 'HAIKU' },
  macro_watcher: { color: '#b18cf0', label: 'MACRO WATCHER', model: 'HAIKU' },
}

function voteCls(action = '') {
  const a = action.toUpperCase()
  if (a === 'BUY')  return styles.voteBuy
  if (a === 'SELL') return styles.voteSell
  return styles.voteHold
}

export function LiveTab({ snapshot: s }: Props) {
  // ── Resizable zones (hooks must run before any early return) ───────────────
  const [sideW, setSideW] = useState(252)
  const [chartH, setChartH] = useState(220)
  const dragRef = useRef<{ kind: 'side' | 'chart'; start: number; startVal: number } | null>(null)

  const onMove = useCallback((e: MouseEvent) => {
    const d = dragRef.current
    if (!d) return
    if (d.kind === 'side') {
      const dx = e.clientX - d.start
      setSideW(Math.max(SIDE_MIN, Math.min(SIDE_MAX, d.startVal + dx)))
    } else {
      const dy = e.clientY - d.start
      setChartH(Math.max(CHART_MIN, Math.min(CHART_MAX, d.startVal + dy)))
    }
  }, [])

  const onUp = useCallback(() => {
    dragRef.current = null
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }, [onMove])

  const startSide = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { kind: 'side', start: e.clientX, startVal: sideW }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [sideW, onMove, onUp])

  const startChart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { kind: 'chart', start: e.clientY, startVal: chartH }
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [chartH, onMove, onUp])

  useEffect(() => () => onUp(), [onUp])

  if (!s) {
    return <div className={styles.loading}><span className="seclbl t-faint">Connecting to agent…</span></div>
  }

  const survFill = Math.min(96, Math.max(4, s.survivalPct)) + '%'
  const buffer = '$' + fmt(s.value - s.deathThreshold)
  const arbAction = s.arbitration?.action ?? '—'

  return (
    <div className={styles.layout}>
      {/* ── SIDEBAR ──────────────────────────────────────── */}
      <aside className={styles.side} style={{ width: sideW, flex: `0 0 ${sideW}px` }}>
      <ScrollArea h="100%" offsetScrollbars>
        {/* Portfolio */}
        <div className={styles.sblock}>
          <div className={`shead ${styles.shead}`}>
            <span className="pip t-dim" />
            <span className="seclbl">Portfolio</span>
          </div>
          <div className={`mono ${styles.pval}`}>
            <span className={styles.pcur}>$</span>{s.valueStr}
          </div>
          <div className={styles.pnlRow}>
            <span className={`mono ${cls(s.pnl)} ${styles.pnlNum}`}>{s.pnlStr}</span>
            <span className={`mono ${cls(s.pnl)} ${styles.pnlPct}`}>{s.pnlPctStr}</span>
            <span className="t-faint" style={{ fontSize: 9 }}>SINCE INCEPTION</span>
          </div>
          {/* Survival */}
          <div className={styles.survRow}>
            <span className="seclbl" style={{ fontSize: '8.5px' }}>Survival</span>
            <span className={`mono pos ${styles.survState}`}>
              {s.isDead ? 'DEAD' : 'SAFE'}
            </span>
          </div>
          <div className={styles.survTrack}>
            <div className={styles.survFill} style={{ width: survFill }} />
            <div className={styles.survMark} style={{ left: survFill }} />
          </div>
          <div className={styles.survCap}>
            <span className="mono t-faint">DEATH ${s.deathThreshold}</span>
            <span className="mono t-faint">BUFFER {buffer}</span>
          </div>
        </div>

        {/* Emotion */}
        <div className={styles.sblock}>
          <div className={`shead ${styles.shead}`} style={{ color: s.emotion.color }}>
            <span className="pip" style={{ background: s.emotion.color }} />
            <span className="seclbl" style={{ color: s.emotion.color }}>Agent State</span>
          </div>
          <div className={styles.emo}>
            <span className={styles.emoDot} style={{ background: s.emotion.color, boxShadow: `0 0 9px ${s.emotion.color}` }} />
            <span className={`${styles.emoState}`} style={{ color: s.emotion.color }}>{s.emotion.state}</span>
          </div>
          <div className={styles.emoQ}>"{s.emotion.quote}"</div>
        </div>

        {/* Agents */}
        <div className={styles.sblock}>
          <div className={`shead blue ${styles.shead}`}>
            <span className="pip" style={{ background: 'var(--blue)' }} />
            <span className="seclbl">Agents · Last Cycle</span>
          </div>
          {s.votes.map((v, i) => {
            const role = (v.agent_name || v.agent || v.agent_role || v.role || '').toLowerCase().replace(/ /g, '_')
            const meta = AGENT_META[role] ?? { color: '#8a99ab', label: role.toUpperCase(), model: '' }
            const action = String(v.action || v.vote || 'HOLD')
            const conf = Number(v.confidence ?? 0)
            return (
              <div key={i} className={styles.agent} style={{ '--c': meta.color } as React.CSSProperties}>
                <div className={styles.agHd}>
                  <span className={`${styles.agName} mono`}>{meta.label}</span>
                  <span className={`${styles.vote} ${voteCls(action)} mono`}>{action}</span>
                  <span className={`${styles.agModel} mono t-faint`}>{meta.model}</span>
                </div>
                {v.reasoning && <div className={styles.agReason}>{String(v.reasoning).slice(0, 120)}</div>}
                <div className={styles.confBar}>
                  <div className={styles.confFill} style={{ width: Math.round(conf * 100) + '%' }} />
                </div>
                <div className={styles.agChips}>
                  <span className={`${styles.chip} mono`}>{Math.round(conf * 100)}% conf</span>
                </div>
              </div>
            )
          })}

          {/* Arbitration */}
          {s.arbitration && Object.keys(s.arbitration).length > 0 && (
            <div className={styles.arb}>
              <div className={styles.arbTop}>
                <span className={`${styles.arbTtl} amber`}>⟁ ARBITRATION</span>
                <span className="mono t-dim" style={{ fontSize: 9 }}>FINAL DECISION</span>
              </div>
              <div className={styles.arbMain}>
                <span className={`mono ${styles.arbAct} ${cls(arbAction === 'BUY' ? 1 : arbAction === 'SELL' ? -1 : 0)}`}>{arbAction}</span>
                {s.arbitration.symbol && <span className={`mono ${styles.arbSym}`}>{String(s.arbitration.symbol)}</span>}
              </div>
              <div className={styles.arbMeta}>
                {s.arbitration.confidence != null && (
                  <div><div className={styles.arbMl}>Confidence</div><div className={`mono ${styles.arbMv}`}>{Number(s.arbitration.confidence).toFixed(2)}</div></div>
                )}
                {s.arbitration.allocation_pct != null && (
                  <div><div className={styles.arbMl}>Allocation</div><div className={`mono ${styles.arbMv}`}>{Number(s.arbitration.allocation_pct).toFixed(0)}%</div></div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Metrics */}
        <div className={styles.sblock}>
          <div className={`shead ${styles.shead}`} style={{ color: 'var(--cyan)' }}>
            <span className="pip" style={{ background: 'var(--cyan)' }} />
            <span className="seclbl">Metrics</span>
          </div>
          <div className={styles.mgrid}>
            {[
              { lbl: 'Cash',         val: '$' + fmt(s.cash) },
              { lbl: 'Peak Value',   val: '$' + fmt(s.peakValue) },
              { lbl: 'Positions',    val: String(s.positions.length) },
              { lbl: 'Hold Streak',  val: String(s.consecutiveHolds) },
            ].map(m => (
              <div key={m.lbl} className={styles.mcell}>
                <div className={styles.mlbl}>{m.lbl}</div>
                <div className={`mono ${styles.mval}`}>{m.val}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Positions */}
        <div className={styles.sblock}>
          <div className={`shead ${styles.shead}`}>
            <span className="pip t-dim" />
            <span className="seclbl">Positions · {s.positions.length}</span>
          </div>
          {s.positions.map(p => (
            <div key={p.sym} className={styles.posRow}>
              <span className={`${styles.pSym}`}>{p.sym}</span>
              <div className={styles.pAllocTrk}><div className={styles.pAllocFill} style={{ width: Math.min(100, p.allocPct) + '%' }} /></div>
              <span className={`mono ${styles.pPnl} ${cls(p.pnlPct)}`}>{pct(p.pnlPct)}</span>
            </div>
          ))}
        </div>
      </ScrollArea>
      </aside>

      {/* vertical resizer (sidebar width) */}
      <div className={styles.vResizer} onMouseDown={startSide} />

      {/* ── MAIN ─────────────────────────────────────────── */}
      <div className={styles.main}>
        {/* Equity */}
        <div className={styles.chartHd}>
          <div className="flex items-center gap-2">
            <span className="pip" style={{ background: 'var(--pos)' }} />
            <span className="seclbl">Equity Curve</span>
            <span className="t-faint mono" style={{ fontSize: 9 }}>· INCEPTION → NOW</span>
          </div>
          <div className={styles.chartVals}>
            {[
              { lbl: 'HIGH',    val: '$' + fmt(Math.max(...s.equity.map(e => e.v), s.value)) },
              { lbl: 'LOW',     val: '$' + fmt(Math.min(...s.equity.map(e => e.v), s.value)) },
              { lbl: 'CURRENT', val: '$' + fmt(s.value) },
            ].map(cv => (
              <div key={cv.lbl}>
                <div className={styles.cvLbl}>{cv.lbl}</div>
                <div className={`mono ${styles.cvVal}`}>{cv.val}</div>
              </div>
            ))}
          </div>
        </div>
        <div className={styles.chartWrap} style={{ height: chartH }}>
          <EquityChart points={s.equity} height={chartH} />
        </div>

        {/* horizontal resizer (chart height) */}
        <div className={styles.hResizer} onMouseDown={startChart} />

        {/* Log */}
        <div className={styles.logHd}>
          <div className="flex items-center gap-2">
            <span className="pip" style={{ background: 'var(--pos)' }} />
            <span className="seclbl">Activity Log</span>
          </div>
          <span className="t-faint mono" style={{ fontSize: '8.5px', letterSpacing: '.12em' }}>NEWEST FIRST</span>
        </div>
        <ActivityLog entries={s.log} />
      </div>
    </div>
  )
}
