/**
 * WASM initialization and typed wrapper for WasmLattice.
 */

export interface StepMetrics {
  generation: number
  entropy: number
  compute_max_age: number
  compute_median_age: number
  compute_mean_age: number
  signal_active: number
  compassion_active: number
  structural: number
  compute: number
  energy: number
  sensor: number
  void: number
  ratios: [number, number, number, number]
}

export interface IWasmLattice {
  step(): string
  step_n(n: number): string
  render_data(): Float32Array
  state_buffer(): Uint8Array
  memory_channel(ch: number): Float32Array
  size(): number
  generation(): number
  census(): string
  set_seed(seed: bigint): void
}

let wasmModule: any = null

export async function initWasm(): Promise<boolean> {
  try {
    // Dynamic import: path is computed at runtime to prevent Rollup resolution
    const wasmPath = '../pkg/uft_ca.js'
    const mod = await import(/* @vite-ignore */ wasmPath)
    await mod.default()
    wasmModule = mod
    return true
  } catch (e) {
    console.warn('WASM module not found. Using mock engine.', e)
    return false
  }
}

export function createLattice(size: number): IWasmLattice {
  if (wasmModule) return new wasmModule.WasmLattice(size)
  return new MockLattice(size)
}

export function createLatticeFromGenome(json: string, size: number): IWasmLattice {
  if (wasmModule) return wasmModule.WasmLattice.from_genome(json, size)
  return new MockLattice(size)
}

class MockLattice implements IWasmLattice {
  private _size: number
  private _gen: number = 0
  private states: Uint8Array

  constructor(size: number) {
    this._size = size
    const n3 = size * size * size
    this.states = new Uint8Array(n3)
    const center = size / 2
    const r = size / 4
    for (let z = 0; z < size; z++) {
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          const dx = x - center, dy = y - center, dz = z - center
          const dist = Math.sqrt(dx*dx + dy*dy + dz*dz)
          const idx = z * size * size + y * size + x
          if (dist < r * 0.6) this.states[idx] = 2
          else if (dist < r * 0.8) this.states[idx] = 1
          else if (dist < r) this.states[idx] = Math.random() < 0.3 ? 3 : 0
          else if (dist < r * 1.1) this.states[idx] = Math.random() < 0.1 ? 4 : 0
        }
      }
    }
  }

  step(): string {
    this._gen++
    const n3 = this._size ** 3
    for (let i = 0; i < n3 * 0.01; i++) {
      const idx = Math.floor(Math.random() * n3)
      if (this.states[idx] !== 0) {
        if (Math.random() < 0.02) this.states[idx] = 0
      } else if (Math.random() < 0.005) {
        this.states[idx] = Math.floor(Math.random() * 4) + 1
      }
    }
    return JSON.stringify(this.mockMetrics())
  }

  step_n(n: number): string {
    for (let i = 0; i < n; i++) this.step()
    return JSON.stringify(this.mockMetrics())
  }

  render_data(): Float32Array {
    const data: number[] = []
    const s = this._size
    for (let z = 0; z < s; z++)
      for (let y = 0; y < s; y++)
        for (let x = 0; x < s; x++) {
          const idx = z*s*s + y*s + x
          if (this.states[idx] !== 0)
            data.push(x, y, z, this.states[idx], Math.random()*20)
        }
    return new Float32Array(data)
  }

  state_buffer(): Uint8Array { return this.states }
  memory_channel(_ch: number): Float32Array { return new Float32Array(this._size**3) }
  size(): number { return this._size }
  generation(): number { return this._gen }
  census(): string { return JSON.stringify(this.mockMetrics()) }
  set_seed(_seed: bigint): void {}

  private mockMetrics(): StepMetrics {
    let s=0,c=0,e=0,se=0,v=0
    for (const st of this.states) {
      switch(st){case 0:v++;break;case 1:s++;break;case 2:c++;break;case 3:e++;break;case 4:se++;break}
    }
    const total = s+c+e+se
    return {
      generation: this._gen, entropy: 0.75,
      compute_max_age: 10+Math.random()*5, compute_median_age: 5+Math.random()*3,
      compute_mean_age: 6+Math.random()*2,
      signal_active: Math.floor(Math.random()*100),
      compassion_active: Math.floor(Math.random()*10),
      structural: s, compute: c, energy: e, sensor: se, void: v,
      ratios: total>0 ? [s/total,c/total,e/total,se/total] : [0,0,0,0],
    }
  }
}
