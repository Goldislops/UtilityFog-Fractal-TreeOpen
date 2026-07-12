// Package AN-1 (issue #2 acceptance audit): camera VIEW PRESETS for the
// 3D view — the unmet half of the "camera controls and view presets"
// criterion (OrbitControls interaction already ships).
//
// Design notes:
//  - Presets are ACTIONS, not persistent state: after any manual orbit a
//    "pressed" preset indicator would silently lie, so the buttons carry
//    no aria-pressed. Activating one repositions the camera and re-aims
//    it at the scene origin; the user remains free to orbit away.
//  - The seam below is PURE and structurally typed so it is directly
//    unit-testable with a recording fake — no three.js/WebGL needed —
//    and NetworkView3D stays a thin binding.

// The structural slice of OrbitControls this seam needs (drei exposes the
// three-stdlib instance through its ref; typing structurally avoids
// importing from a transitive package).
export interface OrbitControlsHandle {
  object: { position: { set(x: number, y: number, z: number): void } }
  target: { set(x: number, y: number, z: number): void }
  update(): void
}

export const CAMERA_PRESETS = {
  // The application's mount default (NetworkView3D's <Canvas camera>).
  default: [50, 50, 50],
  // Overhead: slight z offset keeps the up-vector unambiguous for
  // OrbitControls (a perfectly vertical eye ray degenerates the orbit).
  top: [0, 120, 0.01],
  side: [120, 0, 0],
} as const

export type CameraPresetName = keyof typeof CAMERA_PRESETS

export const CAMERA_PRESET_LABELS: Record<CameraPresetName, string> = {
  default: 'Default view',
  top: 'Top view',
  side: 'Side view',
}

// Reposition the camera to a named preset, re-aim at the origin and
// commit via controls.update(). Returns false (and does nothing) when
// the controls are not mounted yet — activating a preset button during
// the mount interlude is a no-op, never a crash.
export function applyCameraPreset(
  handle: OrbitControlsHandle | null | undefined,
  name: CameraPresetName,
): boolean {
  if (!handle) return false
  const [x, y, z] = CAMERA_PRESETS[name]
  handle.object.position.set(x, y, z)
  handle.target.set(0, 0, 0)
  handle.update()
  return true
}
