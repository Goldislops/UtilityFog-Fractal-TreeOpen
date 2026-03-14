import { create } from 'zustand'
import type { StepMetrics, IWasmLattice } from './wasm'

interface AppState {
  lattice: IWasmLattice | null
  setLattice: (l: IWasmLattice) => void
  playing: boolean
  setPlaying: (p: boolean) => void
  stepsPerFrame: number
  setStepsPerFrame: (n: number) => void
  metrics: StepMetrics | null
  setMetrics: (m: StepMetrics) => void
  renderData: Float32Array | null
  setRenderData: (d: Float32Array) => void
  genomeJson: string | null
  setGenomeJson: (g: string) => void
  gridSize: number
  setGridSize: (s: number) => void
  wasmReady: boolean
  setWasmReady: (r: boolean) => void
}

export const useStore = create<AppState>((set) => ({
  lattice: null, setLattice: (l) => set({ lattice: l }),
  playing: false, setPlaying: (p) => set({ playing: p }),
  stepsPerFrame: 1, setStepsPerFrame: (n) => set({ stepsPerFrame: n }),
  metrics: null, setMetrics: (m) => set({ metrics: m }),
  renderData: null, setRenderData: (d) => set({ renderData: d }),
  genomeJson: null, setGenomeJson: (g) => set({ genomeJson: g }),
  gridSize: 32, setGridSize: (s) => set({ gridSize: s }),
  wasmReady: false, setWasmReady: (r) => set({ wasmReady: r }),
}))
