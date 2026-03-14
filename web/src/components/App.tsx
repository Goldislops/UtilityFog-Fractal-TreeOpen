import React, { useEffect, useCallback } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { useStore } from '../store'
import { initWasm, createLattice, createLatticeFromGenome } from '../wasm'
import VoxelRenderer from './VoxelRenderer'
import MetricsDashboard from './MetricsDashboard'
import GenomeLoader from './GenomeLoader'
import Controls from './Controls'
import ColorLegend from './ColorLegend'

export default function App() {
  const {
    lattice, setLattice, setWasmReady,
    gridSize, genomeJson, setMetrics, setRenderData,
  } = useStore()

  useEffect(() => {
    initWasm().then((ready) => {
      useStore.getState().setWasmReady(ready)
      // Create default lattice
      const lat = createLattice(gridSize)
      setLattice(lat)
      // Initial step to get metrics
      const metricsJson = lat.step()
      setMetrics(JSON.parse(metricsJson))
      setRenderData(lat.render_data())
    })
  }, [])

  const handleGenomeLoad = useCallback((json: string) => {
    useStore.getState().setGenomeJson(json)
    useStore.getState().setPlaying(false)
    try {
      const lat = createLatticeFromGenome(json, gridSize)
      setLattice(lat)
      const metricsJson = lat.step()
      setMetrics(JSON.parse(metricsJson))
      setRenderData(lat.render_data())
    } catch (e) {
      console.error('Failed to load genome:', e)
    }
  }, [gridSize])

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      <Canvas
        camera={{ position: [gridSize * 1.5, gridSize * 1.2, gridSize * 1.5], fov: 50 }}
        gl={{ antialias: true, alpha: false }}
        style={{ background: '#0a0a0f' }}
      >
        <ambientLight intensity={0.4} />
        <directionalLight position={[10, 20, 10]} intensity={0.8} />
        <pointLight position={[-10, -10, -10]} intensity={0.3} color="#6366f1" />
        <VoxelRenderer />
        <OrbitControls
          target={[gridSize/2, gridSize/2, gridSize/2]}
          enableDamping
          dampingFactor={0.05}
        />
      </Canvas>

      {/* UI Overlays */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0,
        padding: '12px 16px',
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        pointerEvents: 'none',
      }}>
        <div style={{ pointerEvents: 'auto' }}>
          <h1 style={{
            fontSize: '18px', fontWeight: 700, color: '#e0e0e0',
            margin: 0, letterSpacing: '0.05em',
          }}>
            UFT Dandelion
          </h1>
          <p style={{ fontSize: '11px', color: '#666', margin: '2px 0 0' }}>
            Living Cellular Automaton in WebAssembly
          </p>
        </div>
        <div style={{ pointerEvents: 'auto' }}>
          <GenomeLoader onLoad={handleGenomeLoad} />
        </div>
      </div>

      <MetricsDashboard />
      <Controls />
      <ColorLegend />
    </div>
  )
}
