// Package AL: the WebGL capability probe's own contract — supported,
// unsupported and THROWING canvas APIs, plus the no-retained-context
// guarantee, exercised through a controlled document.createElement seam.
import { describe, it, expect, afterEach, vi } from 'vitest'
import { probeWebGLSupport } from '../src/viz3d/webglSupport'

type GetContext = (type: string) => unknown

function stubCanvas(getContext: GetContext) {
  const createElement = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    if (tag === 'canvas') {
      return { getContext } as unknown as HTMLCanvasElement
    }
    return createElement(tag)
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('probeWebGLSupport', () => {
  it('supported: a webgl2 context probes true and is explicitly released, not retained', () => {
    const loseContext = vi.fn()
    const getExtension = vi.fn((name: string) =>
      name === 'WEBGL_lose_context' ? { loseContext } : null,
    )
    const getContext = vi.fn((type: string) =>
      type === 'webgl2' ? { getExtension } : null,
    )
    stubCanvas(getContext)
    expect(probeWebGLSupport()).toBe(true)
    expect(getExtension).toHaveBeenCalledWith('WEBGL_lose_context')
    expect(loseContext).toHaveBeenCalledTimes(1) // the probe context is released
  })

  it('supported via webgl1 when webgl2 is absent', () => {
    const getContext = vi.fn((type: string) =>
      type === 'webgl' ? { getExtension: () => null } : null,
    )
    stubCanvas(getContext)
    expect(probeWebGLSupport()).toBe(true)
    expect(getContext).toHaveBeenCalledWith('webgl2')
    expect(getContext).toHaveBeenCalledWith('webgl')
  })

  it('supported even when WEBGL_lose_context is unavailable (release is best-effort)', () => {
    stubCanvas(() => ({ getExtension: () => null }))
    expect(probeWebGLSupport()).toBe(true)
  })

  it('unsupported: both context types null probes false', () => {
    const getContext = vi.fn(() => null)
    stubCanvas(getContext)
    expect(probeWebGLSupport()).toBe(false)
  })

  it('throwing probe: a hostile getContext is contained as unsupported, never thrown', () => {
    stubCanvas(() => {
      throw new Error('hostile canvas API')
    })
    expect(probeWebGLSupport()).toBe(false)
  })

  it('throwing probe: a hostile getExtension is contained too', () => {
    stubCanvas(() => ({
      getExtension: () => {
        throw new Error('hostile extension API')
      },
    }))
    expect(probeWebGLSupport()).toBe(false)
  })

  it('jsdom reality check: no WebGL here, so the UNSTUBBED probe reports false', () => {
    // jsdom has no WebGL implementation — the same environment the gate
    // tests rely on. If this ever flips, the gate tests must be revisited.
    expect(probeWebGLSupport()).toBe(false)
  })
})
