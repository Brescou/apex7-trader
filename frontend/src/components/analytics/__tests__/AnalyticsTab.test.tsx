import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AnalyticsTab } from '../AnalyticsTab'
import type { Snapshot } from '../../../types'

vi.mock('../../../hooks/useApex', () => ({
  useAnalytics: () => ({ accuracy: [], postmortems: [] }),
}))

function makeSnapshot(votes: Snapshot['votes']): Snapshot {
  return {
    value: 1000,
    valueStr: '$1,000.00',
    cash: 1000,
    cashStr: '$1,000.00',
    pnl: 0,
    pnlStr: '+$0.00',
    pnlPct: 0,
    pnlPctStr: '+0.00%',
    peakValue: 1000,
    survivalPct: 100,
    deathThreshold: 50,
    initialBalance: 1000,
    isDead: false,
    positions: [],
    cycle: 1,
    thinking: false,
    mode: 'sim',
    consecutiveHolds: 0,
    votes,
    arbitration: {},
    emotion: { state: 'FOCUSED', color: '#fff', quote: '' },
    equity: [],
    log: [],
    timestamp: new Date().toISOString(),
  }
}

describe('AnalyticsTab agent vote labels', () => {
  it('reads the "agent" key that _build_vote() actually sets, not just agent_role/role', () => {
    // agents/multi.py's vote dicts carry the key "agent" (batch G fixed this
    // for LiveTab.tsx but AnalyticsTab.tsx was missed — Review Finding).
    const snapshot = makeSnapshot([
      { agent: 'technician', action: 'BUY', confidence: 0.8 },
      { agent: 'risk_manager', action: 'HOLD', confidence: 0.5 },
    ])

    render(<AnalyticsTab snapshot={snapshot} />)

    expect(screen.getByText('TECHNICIAN')).toBeInTheDocument()
    expect(screen.getByText('RISK_MANAGER')).toBeInTheDocument()
    expect(screen.queryByText('AGENT 1')).not.toBeInTheDocument()
    expect(screen.queryByText('AGENT 2')).not.toBeInTheDocument()
  })

  it('still falls back to agent_role/role when "agent" is absent', () => {
    const snapshot = makeSnapshot([
      { agent_role: 'analyst', action: 'SELL', confidence: 0.6 },
      { role: 'macro_watcher', action: 'HOLD', confidence: 0.4 },
    ])

    render(<AnalyticsTab snapshot={snapshot} />)

    expect(screen.getByText('ANALYST')).toBeInTheDocument()
    expect(screen.getByText('MACRO_WATCHER')).toBeInTheDocument()
  })
})
