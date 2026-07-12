// Package AB: view failure containment — an unexpected active-view render
// exception must never unmount the application shell.
//
// The WebGL-heavy views are mocked at the module seam (no real WebGL in
// unit tests) with CONTROLLABLE failure flags, so genuine render throws
// exercise the real ViewErrorBoundary inside the real App.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode } from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'
import App from '../src/App'

const failures = { v3d: false, v2d: false }

vi.mock('../src/viz3d/NetworkView3D', () => ({
  default: () => {
    if (failures.v3d) throw new Error('synthetic 3D render failure')
    return <div data-testid="view-3d" />
  },
}))
vi.mock('../src/components/NetworkView2D', () => ({
  default: () => {
    if (failures.v2d) throw new Error('synthetic 2D render failure')
    return <div data-testid="view-2d" />
  },
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
  serverOpen() {
    this.readyState = 1
    this.onopen?.({})
  }
}

const live = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
const shellAlive = () => {
  expect(screen.getByRole('button', { name: '2D View' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '3D View' })).toBeInTheDocument()
  expect(screen.getAllByRole('status')).toHaveLength(1)
  expect(screen.getAllByRole('log')).toHaveLength(1)
}
const reportCount = () =>
  vi.mocked(console.error).mock.calls.filter(args => args[0] === 'View render failed:').length

beforeEach(() => {
  failures.v3d = false
  failures.v2d = false
  vi.stubGlobal('WebSocket', FakeWebSocket)
  FakeWebSocket.instances = []
  vi.spyOn(console, 'log').mockImplementation(() => {})
  // React's own development error output also lands on console.error; the
  // bounded-report assertions filter to the boundary's exact channel.
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('view failure containment', () => {
  it('a throwing 3D view shows an accessible fallback while the shell survives', () => {
    failures.v3d = true
    render(<App />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('The 3D network view failed to render.')
    expect(screen.queryByTestId('view-3d')).not.toBeInTheDocument()
    shellAlive()
    expect(reportCount()).toBe(1) // reported once, not swallowed
  })

  it('a throwing 2D view is contained identically', () => {
    failures.v2d = true
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    expect(screen.getByRole('alert')).toHaveTextContent('The 2D network view failed to render.')
    shellAlive()
    expect(reportCount()).toBe(1)
  })

  it('connection state survives a view failure (badge keeps announcing)', () => {
    failures.v3d = true
    render(<App />)
    act(() => live().serverOpen())
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(FakeWebSocket.instances).toHaveLength(1) // no hidden reconnect
  })

  it('switching away recovers: the healthy view renders with no fallback', () => {
    failures.v3d = true
    render(<App />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByTestId('view-2d')).toBeInTheDocument()
  })

  it('switching back after the failure clears remounts a healthy view (boundary reset)', () => {
    failures.v3d = true
    render(<App />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    failures.v3d = false
    fireEvent.click(screen.getByRole('button', { name: '3D View' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByTestId('view-3d')).toBeInTheDocument()
  })

  it('explicit retry remounts only the failed view', () => {
    failures.v3d = true
    render(<App />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    failures.v3d = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry 3D network view' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByTestId('view-3d')).toBeInTheDocument()
    shellAlive()
  })

  it('repeated failure stays bounded: each retry yields one fallback and one report — no loop', () => {
    failures.v3d = true
    render(<App />)
    expect(reportCount()).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: 'Retry 3D network view' })) // still failing
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(reportCount()).toBe(2) // one more failure, one more report — user-paced, no retry loop
    fireEvent.click(screen.getByRole('button', { name: 'Retry 3D network view' }))
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(reportCount()).toBe(3)
  })

  it('successful views never show the fallback', () => {
    render(<App />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByTestId('view-3d')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByTestId('view-2d')).toBeInTheDocument()
  })

  it('StrictMode: single fallback, singular connection lifecycle, no duplicate live regions', () => {
    failures.v3d = true
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(FakeWebSocket.instances).toHaveLength(2) // documented dev-mode double-mount artifact
    act(() => live().serverOpen())
    expect(screen.getAllByRole('status')).toHaveLength(1)
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
    expect(screen.getAllByRole('log')).toHaveLength(1)
  })
})
