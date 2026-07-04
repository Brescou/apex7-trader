import { useEffect, useRef } from 'react'
import type { EquityPoint } from '../../types'

interface Props {
  points: EquityPoint[]
  height?: number
  color?: string
}

/**
 * SVG area chart for the equity curve.
 * Uses lightweight-charts when available; falls back to an inline SVG path.
 * The SVG fallback is used here to keep the bundle light and avoid a canvas
 * timing issue when the component first mounts with no data.
 */
export function EquityChart({ points, height = 220, color = '#2dd4a0' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Build inline SVG path from points
  if (!points || points.length < 2) {
    return <div style={{ height, background: 'transparent' }} />
  }

  const W = 1000
  const H = height
  const values = points.map(p => p.v)
  const mn = Math.min(...values)
  const mx = Math.max(...values)
  const pad = (mx - mn) * 0.14 || 1
  const lo = mn - pad
  const hi = mx + pad
  const n = points.length

  const pts = values.map((v, i) => [
    (i / (n - 1)) * W,
    H - ((v - lo) / (hi - lo)) * H,
  ])

  const linePath = 'M' + pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' L')
  const areaPath = `${linePath} L${W},${H} L0,${H} Z`
  const lastY = pts[pts.length - 1][1]

  const gradId = 'eqg'

  return (
    <div ref={containerRef} style={{ width: '100%', position: 'relative' }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height, display: 'block' }}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.20" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* Grid lines */}
        {[0.25, 0.5, 0.75].map(f => (
          <line key={f} x1="0" y1={H * f} x2={W} y2={H * f} stroke="#131a23" strokeWidth="1" />
        ))}
        <path d={areaPath} fill={`url(#${gradId})`} />
        <path d={linePath} fill="none" stroke={color} strokeWidth="1.7" />
        <circle cx={W} cy={lastY} r="3.5" fill={color} />
      </svg>
    </div>
  )
}
