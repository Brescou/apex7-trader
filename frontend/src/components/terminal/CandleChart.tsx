import { useMemo, useRef, useState } from 'react'
import type { OhlcvBar } from '../../types'
import styles from './CandleChart.module.css'

interface Props {
  bars: OhlcvBar[]
  height?: number
}

const POS = '#2dd4a0'
const NEG = '#f2596b'
const MA20_COLOR = '#e3b341'
const MA50_COLOR = '#5b9dff'

function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = []
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period) sum -= values[i - period]
    out.push(i >= period - 1 ? sum / period : null)
  }
  return out
}

function fmtVol(v: number): string {
  if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B'
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K'
  return String(v)
}

/**
 * Bloomberg-style candlestick chart: OHLC candles + volume histogram +
 * MA20 / MA50 overlays + price/time axes + interactive crosshair tooltip.
 * Pure SVG, responsive via viewBox. No external chart library.
 */
export function CandleChart({ bars, height = 320 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<number | null>(null)

  const W = 1000
  const H = height
  const padR = 56          // right price axis
  const padB = 22          // bottom time axis
  const volH = 64          // volume pane height
  const gapPV = 10         // gap price/volume
  const plotW = W - padR
  const priceH = H - padB - volH - gapPV

  const model = useMemo(() => {
    if (!bars || bars.length < 2) return null
    const n = bars.length
    const highs = bars.map(b => b.high)
    const lows = bars.map(b => b.low)
    const closes = bars.map(b => b.close)
    const vols = bars.map(b => b.volume || 0)

    const hi = Math.max(...highs)
    const lo = Math.min(...lows)
    const pad = (hi - lo) * 0.08 || 1
    const yHi = hi + pad
    const yLo = lo - pad
    const maxVol = Math.max(...vols, 1)

    const ma20 = sma(closes, 20)
    const ma50 = sma(closes, 50)

    const xOf = (i: number) => (i + 0.5) / n * plotW
    const yOf = (p: number) => ((yHi - p) / (yHi - yLo)) * priceH
    const cw = Math.max(1.2, (plotW / n) * 0.62)

    const priceTicks = 5
    const ticks = Array.from({ length: priceTicks + 1 }, (_, k) => {
      const p = yHi - (k / priceTicks) * (yHi - yLo)
      return { p, y: yOf(p) }
    })

    // time labels (≈6)
    const labelCount = Math.min(6, n)
    const timeLabels = Array.from({ length: labelCount }, (_, k) => {
      const idx = Math.round((k / (labelCount - 1)) * (n - 1))
      return { x: xOf(idx), label: bars[idx].date.slice(5) }
    })

    return { n, yHi, yLo, maxVol, ma20, ma50, xOf, yOf, cw, ticks, timeLabels }
  }, [bars, plotW, priceH])

  if (!model) {
    return <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <span className="seclbl t-faint">Loading chart…</span>
    </div>
  }

  const { n, yHi, yLo, maxVol, ma20, ma50, xOf, yOf, cw, ticks, timeLabels } = model
  const volTop = priceH + gapPV
  const volOf = (v: number) => volH - (v / maxVol) * volH

  const maPath = (ma: (number | null)[]) => {
    let d = ''
    ma.forEach((v, i) => {
      if (v == null) return
      d += (d ? ' L' : 'M') + `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`
    })
    return d
  }

  const onMove = (e: React.MouseEvent) => {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const x = (e.clientX - rect.left) / rect.width * W
    if (x > plotW) { setHover(null); return }
    const i = Math.min(n - 1, Math.max(0, Math.round((x / plotW) * n - 0.5)))
    setHover(i)
  }

  const hb = hover != null ? bars[hover] : null
  const hx = hover != null ? xOf(hover) : 0

  return (
    <div className={styles.wrap}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className={styles.svg}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {/* price grid + axis labels */}
        {ticks.map((t, k) => (
          <g key={k}>
            <line x1={0} y1={t.y} x2={plotW} y2={t.y} stroke="#131a23" strokeWidth={1} />
            <text x={W - 4} y={t.y + 3} textAnchor="end" className={styles.axis}>{t.p.toFixed(2)}</text>
          </g>
        ))}

        {/* time labels */}
        {timeLabels.map((t, k) => (
          <text key={k} x={t.x} y={H - 6} textAnchor="middle" className={styles.axis}>{t.label}</text>
        ))}

        {/* volume histogram */}
        {bars.map((b, i) => {
          const up = b.close >= b.open
          return (
            <rect
              key={`v${i}`}
              x={xOf(i) - cw / 2}
              y={volTop + volOf(b.volume || 0)}
              width={cw}
              height={volH - volOf(b.volume || 0)}
              fill={up ? POS : NEG}
              opacity={0.28}
            />
          )
        })}

        {/* candles */}
        {bars.map((b, i) => {
          const up = b.close >= b.open
          const color = up ? POS : NEG
          const x = xOf(i)
          const yO = yOf(b.open)
          const yC = yOf(b.close)
          const yH = yOf(b.high)
          const yL = yOf(b.low)
          const bodyTop = Math.min(yO, yC)
          const bodyH = Math.max(1, Math.abs(yC - yO))
          return (
            <g key={`c${i}`}>
              <line x1={x} y1={yH} x2={x} y2={yL} stroke={color} strokeWidth={1} />
              <rect x={x - cw / 2} y={bodyTop} width={cw} height={bodyH} fill={color} />
            </g>
          )
        })}

        {/* MA overlays */}
        <path d={maPath(ma50)} fill="none" stroke={MA50_COLOR} strokeWidth={1.3} opacity={0.85} />
        <path d={maPath(ma20)} fill="none" stroke={MA20_COLOR} strokeWidth={1.3} opacity={0.85} />

        {/* crosshair */}
        {hb && (
          <g>
            <line x1={hx} y1={0} x2={hx} y2={priceH} stroke="#3a4654" strokeWidth={1} strokeDasharray="3 3" />
            <line x1={0} y1={yOf(hb.close)} x2={plotW} y2={yOf(hb.close)} stroke="#3a4654" strokeWidth={1} strokeDasharray="3 3" />
            <rect x={W - padR} y={yOf(hb.close) - 8} width={padR} height={16} fill="#1b232f" />
            <text x={W - 4} y={yOf(hb.close) + 3} textAnchor="end" className={styles.axisHi}>{hb.close.toFixed(2)}</text>
          </g>
        )}
      </svg>

      {/* legend */}
      <div className={styles.legend}>
        <span className={styles.lgItem} style={{ color: MA20_COLOR }}>— MA20</span>
        <span className={styles.lgItem} style={{ color: MA50_COLOR }}>— MA50</span>
      </div>

      {/* OHLC readout (hover or last bar) */}
      {(() => {
        const b = hb ?? bars[bars.length - 1]
        if (!b) return null
        const up = b.close >= b.open
        return (
          <div className={styles.readout}>
            <span className={styles.roDate}>{b.date}</span>
            <span>O <b className="mono">{b.open.toFixed(2)}</b></span>
            <span>H <b className="mono">{b.high.toFixed(2)}</b></span>
            <span>L <b className="mono">{b.low.toFixed(2)}</b></span>
            <span>C <b className="mono" style={{ color: up ? POS : NEG }}>{b.close.toFixed(2)}</b></span>
            <span>V <b className="mono">{fmtVol(b.volume || 0)}</b></span>
          </div>
        )
      })()}
    </div>
  )
}
