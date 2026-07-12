// Package X: App view-switching contracts.
//
// The WebGL-heavy view boundaries are MOCKED — jsdom does not render WebGL
// or canvas, so NetworkView3D/NetworkView2D are replaced with typed markers
// at the module seam (exactly the boundary the views own). App's real
// SimBridgeClient wiring stays live against a typed fake WebSocket, so
// connection state and feed delivery are exercised genuinely.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode } from 'react'
import { render, screen, act, fireEvent } from '@testing-library/react'
import App from '../src/App'

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
  serverOpen() {
    this.readyState = 1
    this.onopen?.({})
  }
  serverMessage(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }
}

const live = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1]

beforeEach(() => {
  vi.stubGlobal('WebSocket', FakeWebSocket)
  FakeWebSocket.instances = []
  vi.spyOn(console, 'log').mockImplementation(() => {})
})

afterEach(() => {
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('App view switching', () => {
  it('defaults to the 3D view with semantic pressed state and a labelled region', async () => {
    render(<App />)
    expect(await screen.findByTestId('view-3d')).toBeInTheDocument()
    expect(screen.queryByTestId('view-2d')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: '3D network view' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '3D View' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '2D View' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('switching shows exactly one active view and swaps pressed state + region label', async () => {
    render(<App />)
    await screen.findByTestId('view-3d')
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    expect(await screen.findByTestId('view-2d')).toBeInTheDocument()
    expect(screen.queryByTestId('view-3d')).not.toBeInTheDocument()
    expect(screen.getAllByRole('region')).toHaveLength(1)
    expect(screen.getByRole('region', { name: '2D network view' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2D View' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '3D View' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('switching preserves the persistent connection/status surfaces and feed content', async () => {
    render(<App />)
    await screen.findByTestId('view-3d')
    act(() => live().serverOpen())
    expect(screen.getByRole('status')).toHaveTextContent('Connected')

    act(() => live().serverMessage({ type: 'node_update', payload: { id: 'n1' } }))
    const feed = screen.getByRole('log', { name: 'Event feed' })
    expect(feed.querySelectorAll('[data-event-channel]')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    await screen.findByTestId('view-2d')
    // One status region, one log region — same content, nothing remounted.
    expect(screen.getAllByRole('status')).toHaveLength(1)
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
    expect(screen.getAllByRole('log')).toHaveLength(1)
    expect(
      screen.getByRole('log', { name: 'Event feed' }).querySelectorAll('[data-event-channel]'),
    ).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: '3D View' }))
    await screen.findByTestId('view-3d')
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
    expect(
      screen.getByRole('log', { name: 'Event feed' }).querySelectorAll('[data-event-channel]'),
    ).toHaveLength(1)
  })

  it('StrictMode: one live socket lineage, single status region, no duplicated feed entries', async () => {
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
    await screen.findByTestId('view-3d')
    // Development StrictMode mounts effects twice: the first client is
    // disconnected by its own cleanup; the LAST socket is the live one.
    expect(FakeWebSocket.instances.length).toBe(2)
    act(() => live().serverOpen())
    expect(screen.getAllByRole('status')).toHaveLength(1)
    expect(screen.getByRole('status')).toHaveTextContent('Connected')

    act(() => live().serverMessage({ type: 'node_update', payload: { id: 'once' } }))
    expect(
      screen.getByRole('log', { name: 'Event feed' }).querySelectorAll('[data-event-channel]'),
    ).toHaveLength(1)
  })
})
