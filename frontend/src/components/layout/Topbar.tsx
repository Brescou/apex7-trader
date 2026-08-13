import { useEffect, useState } from 'react'
import { Badge, SegmentedControl, Tabs } from '@mantine/core'
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
      <div className={styles.brand}>
        <div className={styles.logo}>◆</div>
        <div>
          <div className={styles.brandRow}>
            <span className={`mono ${styles.brandName}`}>APEX-7</span>
            <span className={`mono ${styles.ver}`}>v3.2</span>
            {thinking && (
              <Badge variant="outline" color="cyan" className={styles.thinking}>
                THINKING
              </Badge>
            )}
          </div>
          <div className={styles.brandSub}>SURVIVAL TRADER</div>
        </div>
      </div>

      <Tabs
        value={tab}
        onChange={(v) => v && onTabChange(v as Tab)}
        variant="pills"
        classNames={{ list: styles.tabs, tab: styles.tabBtn }}
      >
        <Tabs.List>
          {TABS.map((t) => (
            <Tabs.Tab key={t.key} value={t.key}>
              {t.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>

      <div className={styles.spacer} />

      <SegmentedControl
        value={mode}
        onChange={(v) => onModeChange(v as Mode)}
        data={[
          { label: 'LIVE', value: 'live' },
          { label: 'PAPER', value: 'paper' },
          { label: 'SIM', value: 'sim' },
        ]}
        className={`${styles.mseg} ${styles[`mseg_${mode}`]}`}
        classNames={{ label: styles.mbtn, innerLabel: 'mono', indicator: styles.indicator }}
      />

      <div className={styles.cycleBadge}>
        <span className="t-faint seclbl" style={{ fontSize: 9 }}>CYCLE</span>
        <span className="mono t-mid" style={{ fontSize: 11 }}>{cycle.toLocaleString()}</span>
      </div>

      <Clock />

      <Badge
        variant="dot"
        color={connected ? 'teal' : 'orange'}
        size="sm"
        className={styles.conn}
      >
        {connected ? 'CONNECTED' : 'RECONNECTING'}
      </Badge>
    </header>
  )
}
