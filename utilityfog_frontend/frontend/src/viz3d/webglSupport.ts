// Package AL: narrow WebGL capability probe for the 3D view.
//
// A browser/device without usable WebGL previously hit the raw
// canvas/context failure inside the heavy renderer (the CI Firefox
// headless run died with "Error creating WebGL context"). The probe lets
// the application decide BEFORE mounting the renderer — and before even
// fetching its chunk.
//
// Contract:
//  - NEVER throws: any hostile/broken canvas API reads as "unsupported".
//  - Does not retain the probe canvas or context: the context is
//    explicitly released where the platform provides WEBGL_lose_context,
//    and every reference is dropped either way (the detached canvas is
//    garbage once this returns).
//  - A successful probe means a context could be CREATED — it does NOT
//    guarantee the Three.js renderer will initialize or render (driver
//    blacklists, context-loss at mount time and renderer failures remain
//    possible; those still belong to ViewErrorBoundary).
export function probeWebGLSupport(): boolean {
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl2') ?? canvas.getContext('webgl')
    if (!gl) return false
    const lose = (gl as WebGLRenderingContext).getExtension('WEBGL_lose_context')
    lose?.loseContext()
    return true
  } catch {
    return false
  }
}
