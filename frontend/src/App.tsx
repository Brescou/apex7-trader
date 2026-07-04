import { useState } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useSetMode } from './hooks/useApex'
import { Topbar } from './components/layout/Topbar'
import { LiveTab } from './components/live/LiveTab'
import { TerminalTab } from './components/terminal/TerminalTab'
import { AnalyticsTab } from './components/analytics/AnalyticsTab'
import type { Mode, Tab } from './types'
import styles from './App.module.css'

export default function App() {
  const [tab, setTab] = useState<Tab>('live')
  const { snapshot, connected } = useWebSocket()
  const setMode = useSetMode()

  const handleModeChange = (mode: Mode) => {
    setMode(mode)
  }

  return (
    <div className={styles.app}>
      <Topbar
        tab={tab}
        onTabChange={setTab}
        mode={(snapshot?.mode ?? 'live') as Mode}
        onModeChange={handleModeChange}
        cycle={snapshot?.cycle ?? 0}
        connected={connected}
        thinking={snapshot?.thinking ?? false}
      />
      <div className={styles.content}>
        {tab === 'live'      && <LiveTab snapshot={snapshot} />}
        {tab === 'terminal'  && <TerminalTab />}
        {tab === 'analytics' && <AnalyticsTab snapshot={snapshot} />}
        {tab === 'backtest'  && (
          <div className={styles.placeholder}>
            <span className="seclbl">BACKTEST — coming soon</span>
          </div>
        )}
      </div>
    </div>
  )
}
