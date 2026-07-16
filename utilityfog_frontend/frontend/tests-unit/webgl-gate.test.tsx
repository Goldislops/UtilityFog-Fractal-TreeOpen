// Package AL: the App-level WebGL capability gate. The probe module is
// mocked at its seam (controllable result + call counter); the views are
// mocked like the containment suite so the REAL App, gate, boundary and
// region structure are exercised.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import App from '../src/App'

const probe = { result: false, calls: 0 }

vi.mock('../src/viz3d/webglSupport', () => ({
  probeWebGLSupport: () => {
    probe.calls++
    return probe.result
  },
}))

vi.mock('../src/viz3d/NetworkView3D', () => ({
  default: () => <div data-testid="view-3d" />,
}))
vi.mock('../src/components/NetworkView2D', () => ({
  default: () => <div data-testid="view-2d" />,
}))

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static instances: FakeWebSocket[] = []
  url: string
  readyState = 0
  onopen: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: unknown) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null
  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  send() {}
  close() {
    this.readyState = 3
  }
}

beforeEach(() => {
  probe.result = false
  probe.calls = 0
  vi.stubGlobal('WebSocket', FakeWebSocket)
  FakeWebSocket.instances = []
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('WebGL capability gate', () => {
  it('unsupported: an accessible message and a Use 2D view button render INSIDE the 3D region; the renderer never mounts', async () => {
    render(<App />)
    const region = screen.getByRole('region', { name: '3D network view' })
    expect(region).toHaveTextContent('no usable WebGL support')
    const use2d = screen.getByRole('button', { name: 'Use 2D view' })
    expect(use2d).toHaveClass('webgl-use-2d-button') // 44x44 floor lives in CSS
    expect(screen.queryByTestId('view-3d')).not.toBeInTheDocument()
    // Shell alive: controls, badge, feed.
    expect(screen.getByRole('button', { name: '2D View' })).toBeInTheDocument()
    expect(screen.getAllByRole('status')).toHaveLength(1)
    expect(screen.getAllByRole('log')).toHaveLength(1)
  })

  it('unsupported: exactly ONE probe — rerenders and view switches never re-probe (no loop, no spam)', async () => {
    render(<App />)
    screen.getByRole('button', { name: 'Use 2D view' })
    expect(probe.calls).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    await screen.findByTestId('view-2d')
    fireEvent.click(screen.getByRole('button', { name: '3D View' }))
    screen.getByRole('button', { name: 'Use 2D view' }) // fallback again, from held state
    expect(probe.calls).toBe(1) // still the single probe
    expect(vi.mocked(console.error).mock.calls).toHaveLength(0) // no log spam
  })

  it('no additional SimBridge connection exists on the fallback path', () => {
    render(<App />)
    screen.getByRole('button', { name: 'Use 2D view' })
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('Use 2D view switches to a working, stable 2D view over the SAME connection', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Use 2D view' }))
    expect(await screen.findByTestId('view-2d')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '2D network view' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2D View' })).toHaveAttribute('aria-pressed', 'true')
    expect(FakeWebSocket.instances).toHaveLength(1)
    // Stable: a rerender-provoking interaction leaves it in place.
    fireEvent.click(screen.getByRole('button', { name: '2D View' })) // active no-op
    expect(screen.getByTestId('view-2d')).toBeInTheDocument()
  })

  it('supported: the 3D renderer mounts inside its boundary as before', async () => {
    probe.result = true
    render(<App />)
    expect(await screen.findByTestId('view-3d')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Use 2D view' })).not.toBeInTheDocument()
    expect(probe.calls).toBe(1)
  })

  it('explicit re-probe is user-paced: Check 3D support again recovers when support appears', async () => {
    render(<App />)
    screen.getByRole('button', { name: 'Use 2D view' })
    expect(probe.calls).toBe(1)
    probe.result = true
    fireEvent.click(screen.getByRole('button', { name: 'Check 3D support again' }))
    expect(await screen.findByTestId('view-3d')).toBeInTheDocument()
    expect(probe.calls).toBe(2) // exactly one more probe, on the user's click
  })
})
