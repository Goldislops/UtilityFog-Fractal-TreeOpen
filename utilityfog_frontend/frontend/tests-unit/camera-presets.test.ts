// Package AN-1: the camera view-preset seam, tested pure — no three.js.
import { describe, it, expect } from 'vitest'
import {
  CAMERA_PRESETS,
  CAMERA_PRESET_NAMES,
  CAMERA_PRESET_LABELS,
  applyCameraPreset,
  type OrbitControlsHandle,
} from '../src/viz3d/cameraPresets'

function recordingHandle() {
  const calls: string[] = []
  const handle: OrbitControlsHandle = {
    object: {
      position: {
        set: (x, y, z) => {
          calls.push(`position(${x},${y},${z})`)
        },
      },
    },
    target: {
      set: (x, y, z) => {
        calls.push(`target(${x},${y},${z})`)
      },
    },
    update: () => {
      calls.push('update()')
    },
  }
  return { handle, calls }
}

describe('CAMERA_PRESETS', () => {
  it('CAMERA_PRESET_NAMES is the stable, exhaustive, unique key tuple for the map and labels', () => {
    // The exported tuple is what rendering and tests iterate — it must
    // stay in lockstep with the coordinate map and the labels.
    expect([...CAMERA_PRESET_NAMES].sort()).toEqual(Object.keys(CAMERA_PRESETS).sort())
    expect([...CAMERA_PRESET_NAMES].sort()).toEqual(Object.keys(CAMERA_PRESET_LABELS).sort())
    expect(new Set(CAMERA_PRESET_NAMES).size).toBe(CAMERA_PRESET_NAMES.length)
  })

  it('every preset is three finite numbers, every preset has a label, and positions are distinct', () => {
    const seen = new Set<string>()
    for (const name of CAMERA_PRESET_NAMES) {
      const pos = CAMERA_PRESETS[name]
      expect(pos).toHaveLength(3)
      for (const coord of pos) expect(Number.isFinite(coord)).toBe(true)
      expect(CAMERA_PRESET_LABELS[name]).toBeTruthy()
      seen.add(pos.join(','))
    }
    expect(seen.size).toBe(CAMERA_PRESET_NAMES.length)
  })

  it("the default preset matches the application's mount camera position", () => {
    // NetworkView3D mounts <Canvas camera={{ position: [50, 50, 50] }}> —
    // the preset must return the user to exactly that framing.
    expect(CAMERA_PRESETS.default).toEqual([50, 50, 50])
  })
})

describe('applyCameraPreset', () => {
  it('repositions, re-aims at the origin, and commits — in that order', () => {
    const { handle, calls } = recordingHandle()
    expect(applyCameraPreset(handle, 'top')).toBe(true)
    expect(calls).toEqual(['position(0,120,0.01)', 'target(0,0,0)', 'update()'])
  })

  it.each([...CAMERA_PRESET_NAMES])(
    'preset %s applies its own coordinates',
    (name) => {
      const { handle, calls } = recordingHandle()
      applyCameraPreset(handle, name)
      const [x, y, z] = CAMERA_PRESETS[name]
      expect(calls[0]).toBe(`position(${x},${y},${z})`)
    },
  )

  it('unmounted controls (null/undefined) are a safe no-op returning false', () => {
    expect(applyCameraPreset(null, 'default')).toBe(false)
    expect(applyCameraPreset(undefined, 'side')).toBe(false)
  })
})
