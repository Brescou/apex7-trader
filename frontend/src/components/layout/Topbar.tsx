import { useEffect, useState } from 'react'
import type { Mode, Tab } from '../../types'
import styles from './Topbar.module.css'

interface Props {
  tab: Tab
  onTabChange: (t: Tab) => void
  mode: Mode
  onModeChange: (m: Mode) => void
  cycle: number
  connected: boolean
  thinking: boolean
}

function Clock() {
  const [time, setTime] = useState('')
  useEffect(() => {
    const tick = () => {
      const d = new Date()
      setTime(d.toLocaleTimeString('en-US', { hour12: false }) + ' EST')
    }
    tick()
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
  }, [])
  return <span className={`mono ${styles.clock}`}>{time}</span>
}

const TABS: { key: Tab; label: string }[] = [
  { key: 'live',      label: 'LIVE' },
  { key: 'terminal',  label: 'TERMINAL' },
  { key: 'analytics', label: 'ANALYTICS' },
  { key: 'backtest',  label: 'BACKTEST' },
]

export function Topbar({ tab, onTabChange, mode, onModeChange, cycle, connected, thinking }: Props) {
  return (
    <header className={styles.topbar}>
      {/* Brand */}
      <div className={styles.brand}>
        <div className={styles.logo}>◆</div>
        <div>
          <div className={styles.brandRow}>
            <span className={`mono ${styles.brandName}`}>APEX-7</span>
            <span className={`mono ${styles.ver}`}>v3.2</span>
            {thinking && <span className={`mono ${styles.thinking}`}>⟳ THINKING</span>}
          </div>
          <div className={styles.brandSub}>SURVIVAL TRADER</div>
        </div>
      </div>

      {/* Tabs */}
      <nav className={styles.tabs}>
        {TABS.map(t => (
          <button
            key={t.key}
            className={`${styles.tabBtn} ${tab === t.key ? styles.tabOn : ''}`}
            onClick={() => onTabChange(t.key as Tab)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className={styles.spacer} />

      {/* Mode toggle */}
      <div className={styles.mseg}>
        {(['live', 'paper', 'sim'] as Mode[]).map(m => (
          <button
            key={m}
            className={`mono ${styles.mbtn} ${styles[`mbtn_${m}`]} ${mode === m ? styles.mbtnOn : ''}`}
            onClick={() => onModeChange(m)}
          >
            {m.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Cycle */}
      <div className={styles.cycleBadge}>
        <span className="t-faint seclbl" style={{ fontSize: 9 }}>CYCLE</span>
        <span className="mono t-mid" style={{ fontSize: 11 }}>{cycle.toLocaleString()}</span>
      </div>

      <Clock />

      {/* Connection */}
      <div className={`${styles.conn} ${connected ? styles.connOk : styles.connErr}`}>
        <span className={styles.dot} />
        {connected ? 'CONNECTED' : 'RECONNECTING'}
      </div>
    </header>
  )
}
