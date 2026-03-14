import React from 'react'
import { useStore } from '../store'

const panel: React.CSSProperties = {
  position: 'absolute',
  bottom: 16,
  left: 16,
  background: 'rgba(10, 10, 15, 0.85)',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 8,
  padding: '12px 16px',
  minWidth: 220,
  fontSize: 12,
  fontFamily: 'monospace',
  color: '#e0e0e0',
  backdropFilter: 'blur(8px)',
}

const row: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', margin: '3px 0',
}

const label: React.CSSProperties = { color: '#888' }
const value: React.CSSProperties = { fontWeight: 600 }

const barContainer: React.CSSProperties = {
  display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden',
  marginTop: 8, marginBottom: 4,
}

export default function MetricsDashboard() {
  const metrics = useStore((s) => s.metrics)
  if (!metrics) return null

  const { ratios } = metrics
  const barColors = ['#3b82f6', '#10b981', '#f59e0b', '#a855f7']
  const barLabels = ['STR', 'CMP', 'ENR', 'SEN']

  return (
    <div style={panel}>
      <div style={{ fontWeight: 700, marginBottom: 6, color: '#a0a0a0', letterSpacing: '0.1em', fontSize: 10 }}>
        METRICS
      </div>
      <div style={row}><span style={label}>Generation</span><span style={value}>{metrics.generation.toLocaleString()}</span></div>
      <div style={row}><span style={label}>Entropy</span><span style={value}>{metrics.entropy.toFixed(3)}</span></div>
      <div style={row}><span style={label}>Max Age</span><span style={{...value, color: '#10b981'}}>{metrics.compute_max_age.toFixed(1)}</span></div>
      <div style={row}><span style={label}>Median Age</span><span style={value}>{metrics.compute_median_age.toFixed(1)}</span></div>
      <div style={row}><span style={label}>Signal Active</span><span style={{...value, color: '#a855f7'}}>{metrics.signal_active}</span></div>
      <div style={row}><span style={label}>Compassion</span><span style={{...value, color: '#f59e0b'}}>{metrics.compassion_active}</span></div>

      {/* State ratio bar */}
      <div style={barContainer}>
        {ratios.map((r, i) => (
          <div key={i} style={{
            width: `${r * 100}%`,
            background: barColors[i],
            transition: 'width 0.3s ease',
          }} />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: '#666' }}>
        {barLabels.map((l, i) => (
          <span key={i} style={{ color: barColors[i] }}>{l} {(ratios[i] * 100).toFixed(0)}%</span>
        ))}
      </div>
    </div>
  )
}
