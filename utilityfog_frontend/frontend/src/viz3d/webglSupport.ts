// Package AL: narrow WebGL capability probe for the 3D view.
//
// A browser/device without usable WebGL previously hit the raw
// canvas/context failure inside the heavy renderer (the CI Firefox
// headless run died with "Error creating WebGL context"). The probe lets
// the application decide BEFORE mounting the renderer — and before even
// fetching its chunk.
//
// Contract:
//  - Probes the renderer's own context set, in the renderer's preference
//    order: webgl2, then webgl, then experimental-webgl (the prefixed id
//    older engines expose; Three.js accepts a context of that kind too).
//  - NEVER throws: any hostile/broken canvas API reads as "unsupported".
//  - Does not retain the probe canvas or context: the context is
//    explicitly released where the platform provides WEBGL_lose_context,
//    and every reference is dropped either way (the detached canvas is
//    garbage once this returns).
//  - A successful probe means a context could be CREATED — it does NOT
//    guarantee the Three.js renderer will initialize or render (driver
//    blacklists, context-loss at mount time and renderer failures remain
//    possible; those still belong to ViewErrorBoundary).

// experimental-webgl resolves through the string overload of getContext,
// which is typed as the broad RenderingContext union — narrow structurally
// (a WebGL context of any vintage exposes getExtension) instead of
// asserting a concrete class.
function isReleasableWebGLContext(
  ctx: NonNullable<ReturnType<HTMLCanvasElement['getContext']>>,
): ctx is WebGLRenderingContext | WebGL2RenderingContext {
  return typeof (ctx as { getExtension?: unknown }).getExtension === 'function'
}

export function probeWebGLSupport(): boolean {
  try {
    const canvas = document.createElement('canvas')
    const gl =
      canvas.getContext('webgl2') ??
      canvas.getContext('webgl') ??
      canvas.getContext('experimental-webgl')
    if (!gl) return false
    if (isReleasableWebGLContext(gl)) {
      gl.getExtension('WEBGL_lose_context')?.loseContext()
    }
    return true
  } catch {
    return false
  }
}
