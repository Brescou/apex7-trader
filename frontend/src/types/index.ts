// APEX-7 — shared TypeScript types

export type Mode = 'live' | 'paper' | 'sim'
export type Tab  = 'live' | 'terminal' | 'analytics' | 'backtest'

export interface Position {
  sym: string
  shares: number
  avgPrice: number
  lastPrice: number
  value: number
  pnlPct: number
  allocPct: number
  layers: number
  openedAt: string
}

export interface Emotion {
  state: string
  color: string
  quote: string
}

export interface EquityPoint {
  t: string
  v: number
}

export interface LogEntry {
  t: string
  msg: string
  level: string
}

export interface AgentVote {
  agent?: string
  agent_role?: string
  role?: string
  action?: string
  vote?: string
  confidence?: number
  reasoning?: string
  [key: string]: unknown
}

export interface Arbitration {
  action?: string
  symbol?: string
  confidence?: number
  allocation_pct?: number
  emotion?: string
  [key: string]: unknown
}

export interface Snapshot {
  // Portfolio
  value: number
  valueStr: string
  cash: number
  cashStr: string
  pnl: number
  pnlStr: string
  pnlPct: number
  pnlPctStr: string
  peakValue: number
  survivalPct: number
  deathThreshold: number
  initialBalance: number
  isDead: boolean
  positions: Position[]
  // Agent
  cycle: number
  thinking: boolean
  mode: Mode
  consecutiveHolds: number
  votes: AgentVote[]
  arbitration: Arbitration
  emotion: Emotion
  // Chart
  equity: EquityPoint[]
  // Log
  log: LogEntry[]
  timestamp: string
}

export interface WsMessage {
  type: 'snapshot' | 'agent_votes'
  data: unknown
}

// Market
export interface MacroItem {
  name: string
  value: string | number
  change?: string | number
  sub?: string
}

export interface WatchlistItem {
  symbol: string
  price: number
  change: number
  changePct: number
  rsi?: number
  macdHist?: number
  volume?: number
}

export interface SectorItem {
  name: string
  change: number
  changePct: number
}

// Analytics
export interface AgentAccuracy {
  role: string
  total: number
  correct: number
  accuracy: number
  validated: boolean
}

export interface Postmortem {
  sym: string
  entryPrice: number
  exitPrice: number
  pnlPct: number
  holdDays: number
  lesson: string
}
