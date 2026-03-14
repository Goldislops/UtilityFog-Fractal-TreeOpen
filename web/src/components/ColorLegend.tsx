import React from 'react'

const colors = [
  { name: 'STRUCTURAL', color: '#3b82f6', desc: 'Shell / body' },
  { name: 'COMPUTE', color: '#10b981', desc: 'Ganglia / brain' },
  { name: 'ENERGY', color: '#f59e0b', desc: 'Mycelium / fuel' },
  { name: 'SENSOR', color: '#a855f7', desc: 'Nerve endings' },
]

const panel: React.CSSProperties = {
  position: 'absolute',
  top: 60,
  right: 16,
  background: 'rgba(10, 10, 15, 0.7)',
  border: '1px solid rgba(255,255,255,0.06)',
  borderRadius: 6,
  padding: '8px 12px',
  fontSize: 10,
  fontFamily: 'monospace',
  color: '#888',
}

export default function ColorLegend() {
  return (
    <div style={panel}>
      {colors.map((c) => (
        <div key={c.name} style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '2px 0' }}>
          <div style={{ width: 8, height: 8, borderRadius: 2, background: c.color }} />
          <span style={{ color: c.color, minWidth: 80 }}>{c.name}</span>
          <span>{c.desc}</span>
        </div>
      ))}
    </div>
  )
}
