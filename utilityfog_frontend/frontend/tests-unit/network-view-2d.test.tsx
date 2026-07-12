// Package Z: NetworkView2D ingress survival — the previously excluded 2D
// surface.
//
// DOCUMENTED CANVAS BOUNDARY: jsdom does not implement canvas 2D contexts.
// getContext is mocked to return null — exactly the component's own guarded
// early-return path — so these tests validate SUBSCRIPTION and INGRESS
// behavior (survival, recovery, counts) and deliberately claim NOTHING
// about pixel output. Visual rendering stays owned by the Playwright/
// ui-smoke lane.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode } from 'react'
import { render, screen, act } from '@testing-library/react'
import NetworkView2D from '../src/components/NetworkView2D'
import type { SimBridgeClient } from '../src/ws/SimBridgeClient'

class StubSimClient {
  listeners = new Map<string, Set<(data?: unknown) => void>>()
  on(event: string, cb: (data?: unknown) => void) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set())
    this.listeners.get(event)!.add(cb)
  }
  off(event: string, cb: (data?: unknown) => void) {
    this.listeners.get(event)?.delete(cb)
  }
  emit(event: string, data?: unknown) {
    this.listeners.get(event)?.forEach(cb => cb(data))
  }
  totalListeners() {
    let n = 0
    this.listeners.forEach(set => (n += set.size))
    return n
  }
}

let stub: StubSimClient
const asClient = () => stub as unknown as SimBridgeClient
const emit = (channel: string, payload?: unknown) => act(() => stub.emit(channel, payload))
const counts = () => screen.getByText(/Nodes: \d+ \| Edges: \d+/).textContent

const VALID_NET = {
  nodes: [
    { id: 'n1', position: [1, 2, 3], connections: [], status: 'active' },
    { id: 'n2', position: [4, 5, 6], connections: [], status: 'active' },
  ],
  edges: [{ id: 'e1', source: 'n1', target: 'n2', strength: 1 }],
}

beforeEach(() => {
  stub = new StubSimClient()
  // The documented jsdom canvas boundary (see header note).
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('NetworkView2D ingress survival', () => {
  it('mounts empty and applies a valid network_update (counts reflect admitted records)', () => {
    render(<NetworkView2D simClient={asClient()} />)
    expect(counts()).toBe('Nodes: 0 | Edges: 0')
    emit('network_update', VALID_NET)
    expect(counts()).toBe('Nodes: 2 | Edges: 1')
  })

  it('survives hostile network_update payloads without crashing or admitting garbage', () => {
    render(<NetworkView2D simClient={asClient()} />)
    emit('network_update', VALID_NET)
    const hostileNode = {
      id: 'h',
      get position(): unknown {
        throw new Error('hostile position')
      },
    }
    const hostileEdge = {
      id: 'he',
      source: 'n1',
      get target(): unknown {
        throw new Error('hostile target')
      },
    }
    const hostilePayloads: unknown[] = [
      null,
      'junk',
      42,
      { nodes: 'not-an-array', edges: { length: 3 } },
      { nodes: [hostileNode, null, { id: 'ghost' }], edges: [hostileEdge, null, 'x', { id: 'e2', source: 9, target: 'n2' }] },
    ]
    for (const payload of hostilePayloads) {
      expect(() => emit('network_update', payload)).not.toThrow()
    }
    // The wholesale hostile batch admitted nothing valid: nodes list was
    // REPLACED by the sanitized (empty) result; edges likewise.
    expect(counts()).toBe('Nodes: 0 | Edges: 0')
    expect(screen.getByText(/Nodes: 0/)).toBeInTheDocument() // still mounted
  })

  it('recovers on the next valid event after hostile input', () => {
    render(<NetworkView2D simClient={asClient()} />)
    emit('network_update', { nodes: [{ id: 'bad' }], edges: [null] })
    expect(counts()).toBe('Nodes: 0 | Edges: 0')
    emit('network_update', VALID_NET)
    expect(counts()).toBe('Nodes: 2 | Edges: 1')
  })

  it('node_update path: valid admitted, positionless ghost excluded, last valid preserved', () => {
    render(<NetworkView2D simClient={asClient()} />)
    emit('node_update', { id: 'a', position: [1, 1, 1], connections: [], status: 'active' })
    expect(counts()).toBe('Nodes: 1 | Edges: 0')
    emit('node_update', { id: 'ghost', status: 'active' }) // unknown, positionless: excluded
    expect(counts()).toBe('Nodes: 1 | Edges: 0')
    emit('node_update', { id: 'a', status: 'error' }) // merge keeps last valid position
    expect(counts()).toBe('Nodes: 1 | Edges: 0')
    expect(() => emit('node_update', { get id(): unknown { throw new Error('hostile') } })).not.toThrow()
    expect(counts()).toBe('Nodes: 1 | Edges: 0')
  })

  it('produces no console-error storm under a hostile burst', () => {
    render(<NetworkView2D simClient={asClient()} />)
    for (let i = 0; i < 50; i++) {
      emit('node_update', { id: `g${i}` }) // 50 rejected ghosts
      emit('network_update', 'junk')
    }
    // Ingress rejection is silent by design at this boundary; the only
    // mocked console.error must stay uncalled.
    expect(vi.mocked(console.error)).not.toHaveBeenCalled()
    expect(counts()).toBe('Nodes: 0 | Edges: 0')
  })

  it('unmount unsubscribes both channels; StrictMode leaves exactly one subscription set', () => {
    const { unmount } = render(
      <StrictMode>
        <NetworkView2D simClient={asClient()} />
      </StrictMode>,
    )
    expect(stub.totalListeners()).toBe(2) // network_update + node_update, once each
    emit('network_update', VALID_NET)
    expect(counts()).toBe('Nodes: 2 | Edges: 1') // no double-application
    unmount()
    expect(stub.totalListeners()).toBe(0)
  })
})
