import { Badge, ScrollArea } from '@mantine/core'
import { useAnalytics } from '../../hooks/useApex'
import type { Snapshot } from '../../types'
import styles from './AnalyticsTab.module.css'

interface Props { snapshot: Snapshot | null }

function pct(n: number) { return (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%' }
function cls(n: number)  { return n >= 0 ? 'pos' : 'neg' }

const AGENT_META: Record<string, { color: string }> = {
  technician:    { color: '#5b9dff' },
  analyst:       { color: '#2dd4a0' },
  risk_manager:  { color: '#f0934d' },
  macro_watcher: { color: '#b18cf0' },
  economist:     { color: '#e8c547' },
  geopolitician: { color: '#e07070' },
}

export function AnalyticsTab({ snapshot: s }: Props) {
  const { accuracy, postmortems } = useAnalytics()

  const value   = s?.value ?? 1000
  const pnl     = value - (s?.initialBalance ?? 1000)
  const pnlPct  = pnl / (s?.initialBalance ?? 1000) * 100
  const posCount = s?.positions.length ?? 0

  const stats = [
    { lbl: 'Portfolio Value', val: '$' + (value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }), sub: 'mark-to-market', cls: 'pos' },
    { lbl: 'Total P&L',       val: (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2), sub: pct(pnlPct) + ' since inception', cls: cls(pnl) },
    { lbl: 'Open Positions',  val: String(posCount), sub: 'active' },
    { lbl: 'Agent Cycle',     val: String(s?.cycle ?? 0), sub: 'completed cycles' },
    { lbl: 'Hold Streak',     val: String(s?.consecutiveHolds ?? 0), sub: 'consecutive holds' },
    { lbl: 'Mode',            val: (s?.mode ?? '—').toUpperCase(), sub: 'execution mode' },
    { lbl: 'Peak Value',      val: '$' + (s?.peakValue ?? value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }), sub: 'all-time high', cls: 'pos' },
    { lbl: 'Death Threshold', val: '$' + (s?.deathThreshold ?? 50), sub: 'survival floor', cls: 'neg' },
  ]

  return (
    <ScrollArea h="100%" offsetScrollbars>
    <div className={styles.ana}>
      {/* KPI grid */}
      <div className={styles.statGrid}>
        {stats.map(st => (
          <div key={st.lbl} className={styles.statCard}>
            <div className={styles.statLbl}>{st.lbl}</div>
            <div className={`mono ${styles.statVal} ${st.cls ?? ''}`}>{st.val}</div>
            <div className={styles.statSub}>{st.sub}</div>
          </div>
        ))}
      </div>

      <div className={styles.row2}>
        {/* Agent accuracy */}
        <div className={styles.panel}>
          <div className={styles.panelHd} style={{ color: 'var(--blue)' }}>
            <span className="pip" style={{ background: 'var(--blue)' }} />
            <span className="seclbl">Agent Accuracy · Market-Validated</span>
          </div>
          {accuracy.length === 0 && (
            <div className="t-faint seclbl" style={{ fontSize: 9, padding: '12px 0' }}>
              No evaluated trades yet — needs ≥5 resolved votes per agent.
            </div>
          )}
          {accuracy.map(a => {
            const role = (a.role ?? '').toLowerCase().replace(/ /g, '_')
            const color = AGENT_META[role]?.color ?? 'var(--mid)'
            return (
              <div key={a.role} className={styles.rankRow}>
                <span className={styles.rankName} style={{ color }}>{a.role?.toUpperCase()}</span>
                <div className={styles.rankBar}>
                  <div className={styles.rankFill} style={{ width: a.accuracy + '%', background: color }} />
                </div>
                <span className={`mono ${styles.rankAcc}`}>{a.accuracy.toFixed(0)}%</span>
                <Badge
                  variant="outline"
                  color={a.validated ? 'teal' : 'yellow'}
                  className={styles.badge}
                >
                  {a.validated ? '✓ VALIDATED' : '⏳ CALIBRATING'}
                </Badge>
              </div>
            )
          })}

          {/* Current votes summary */}
          {s && s.votes.length > 0 && (
            <>
              <div className={styles.divider} />
              <div className={styles.panelHd} style={{ color: 'var(--amber)', marginBottom: 12 }}>
                <span className="pip" style={{ background: 'var(--amber)' }} />
                <span className="seclbl">Last Cycle · Agent Votes</span>
              </div>
              {s.votes.map((v, i) => {
                const action = String(v.action || v.vote || 'HOLD').toUpperCase()
                const conf   = Number(v.confidence ?? 0)
                const role   = String(v.agent || v.agent_role || v.role || `Agent ${i + 1}`)
                const roleLower = role.toLowerCase().replace(/ /g, '_')
                const color  = AGENT_META[roleLower]?.color ?? 'var(--mid)'
                return (
                  <div key={i} className={styles.voteRow}>
                    <span style={{ color, fontSize: 10, fontWeight: 700, width: 110 }}>{role.toUpperCase()}</span>
                    <span className={`mono ${action === 'BUY' ? 'pos' : action === 'SELL' ? 'neg' : 't-dim'}`} style={{ fontSize: 11, fontWeight: 700 }}>{action}</span>
                    <span className="mono t-faint" style={{ fontSize: 9 }}>{(conf * 100).toFixed(0)}% conf</span>
                  </div>
                )
              })}
            </>
          )}
        </div>

        {/* Postmortem */}
        <div className={styles.panel}>
          <div className={styles.panelHd} style={{ color: 'var(--pos)' }}>
            <span className="pip" style={{ background: 'var(--pos)' }} />
            <span className="seclbl">Postmortem · Closed Trades</span>
          </div>
          {postmortems.length === 0 && (
            <div className="t-faint seclbl" style={{ fontSize: 9, padding: '12px 0' }}>
              No closed trades yet — postmortem runs daily at configured hour.
            </div>
          )}
          {postmortems.map((pm, i) => (
            <div key={i} className={styles.pmRow}>
              <div className={styles.pmHd}>
                <div className="flex items-center gap-2">
                  <span className={styles.pmSym}>{pm.sym}</span>
                  <span className="mono t-faint" style={{ fontSize: 9 }}>held {pm.holdDays}d</span>
                </div>
                <span className={`mono ${styles.pmPnl} ${cls(pm.pnlPct)}`}>{pct(pm.pnlPct)}</span>
              </div>
              {pm.lesson && <div className={styles.pmLesson}>{pm.lesson}</div>}
            </div>
          ))}

          {/* Recent trades from live data */}
          {s && s.positions.length > 0 && (
            <>
              <div className={styles.divider} />
              <div className={styles.panelHd} style={{ marginBottom: 12 }}>
                <span className="pip t-dim" />
                <span className="seclbl">Open Positions · Detail</span>
              </div>
              {s.positions.map(p => (
                <div key={p.sym} className={styles.pmRow}>
                  <div className={styles.pmHd}>
                    <div className="flex items-center gap-2">
                      <span className={styles.pmSym}>{p.sym}</span>
                      <span className="mono t-faint" style={{ fontSize: 9 }}>{p.shares.toFixed(3)} sh · {p.allocPct.toFixed(1)}% alloc</span>
                    </div>
                    <span className={`mono ${styles.pmPnl} ${cls(p.pnlPct)}`}>{pct(p.pnlPct)}</span>
                  </div>
                  <div className="mono t-faint" style={{ fontSize: 9, marginTop: 4 }}>
                    avg ${p.avgPrice.toFixed(2)} → last ${p.lastPrice.toFixed(2)}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
    </ScrollArea>
  )
}
