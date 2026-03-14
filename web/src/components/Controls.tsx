import React from 'react'
import { useStore } from '../store'

const panel: React.CSSProperties = {
  position: 'absolute',
  bottom: 16,
  right: 16,
  background: 'rgba(10, 10, 15, 0.85)',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 8,
  padding: '12px 16px',
  fontSize: 12,
  fontFamily: 'monospace',
  color: '#e0e0e0',
  backdropFilter: 'blur(8px)',
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
}

const btn: React.CSSProperties = {
  background: 'rgba(16, 185, 129, 0.15)',
  border: '1px solid rgba(16, 185, 129, 0.3)',
  color: '#6ee7b7',
  padding: '8px 16px',
  borderRadius: 6,
  cursor: 'pointer',
  fontSize: 13,
  fontFamily: 'monospace',
  fontWeight: 600,
  transition: 'all 0.2s',
}

export default function Controls() {
  const { playing, setPlaying, stepsPerFrame, setStepsPerFrame, lattice, setMetrics, setRenderData } = useStore()

  const handleStep = () => {
    if (!lattice) return
    const json = lattice.step()
    setMetrics(JSON.parse(json))
    setRenderData(lattice.render_data())
  }

  return (
    <div style={panel}>
      <div style={{ fontWeight: 700, color: '#a0a0a0', letterSpacing: '0.1em', fontSize: 10 }}>
        CONTROLS
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          style={{
            ...btn,
            background: playing ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
            borderColor: playing ? 'rgba(239, 68, 68, 0.3)' : 'rgba(16, 185, 129, 0.3)',
            color: playing ? '#fca5a5' : '#6ee7b7',
          }}
          onClick={() => setPlaying(!playing)}
        >
          {playing ? 'Pause' : 'Play'}
        </button>
        <button style={btn} onClick={handleStep}>Step</button>
      </div>
      <div>
        <label style={{ color: '#888', fontSize: 10 }}>Steps/Frame: {stepsPerFrame}</label>
        <input
          type="range"
          min={1}
          max={50}
          value={stepsPerFrame}
          onChange={(e) => setStepsPerFrame(parseInt(e.target.value))}
          style={{ width: '100%', marginTop: 4 }}
        />
      </div>
    </div>
  )
}
