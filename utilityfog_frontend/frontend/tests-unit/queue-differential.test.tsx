// Package AF (audit redesign): DIFFERENTIAL testing — for every
// non-overflowing trace, the queue-delivered final store state must equal
// a plain sequential reference reducer built from the same validators the
// store uses. Includes the two exact counterexamples from Jack's audit.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useEventQueue } from '../src/viz3d/useEventQueue'
import { SimBridgeClient } from '../src/ws/SimBridgeClient'
import { applyNodeUpdate, sanitizeNodeList } from '../src/viz3d/nodeValidation'
import { sanitizeEdgeList } from '../src/viz3d/edgeValidation'
import type { NetworkNode, NetworkEdge } from '../src/ws/SimBridgeClient'

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

type TraceEvent = { type: 'node_update' | 'network_update'; payload: unknown } | { type: 'rerender' }

// The sequential reference: exactly what the old closure queue delivered —
// every event applied in arrival order through the store's own validators.
function referenceReduce(trace: TraceEvent[]): { nodes: NetworkNode[]; edges: NetworkEdge[] } {
  let nodes: NetworkNode[] = []
  let edges: NetworkEdge[] = []
  for (const event of trace) {
    if (event.type === 'rerender') continue
    if (event.type === 'node_update') {
      nodes = applyNodeUpdate(nodes, event.payload)
    } else {
      const d = event.payload as { nodes?: unknown; edges?: unknown } | null
      if (!d || typeof d !== 'object') continue
      if (d.nodes === undefined && d.edges === undefined) continue
      if (Array.isArray(d.nodes)) nodes = sanitizeNodeList(d.nodes, nodes)
      edges = sanitizeEdgeList(d.edges, edges)
    }
  }
  return { nodes, edges }
}

let client: SimBridgeClient
const socket = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1]

// Drive one trace through the real queue against real-validator handlers;
// rerender events swap in FRESH handler objects that keep writing to the
// same state (proving no subscription gap and newest-handler delivery).
async function queueReduce(trace: TraceEvent[]) {
  const state = { nodes: [] as NetworkNode[], edges: [] as NetworkEdge[] }
  const makeHandlers = () => ({
    updateNode: (p: unknown) => {
      state.nodes = applyNodeUpdate(state.nodes, p)
    },
    setNetwork: (nodes: unknown, edges: unknown) => {
      if (Array.isArray(nodes)) state.nodes = sanitizeNodeList(nodes, state.nodes)
      state.edges = sanitizeEdgeList(edges, state.edges)
    },
  })
  const view = renderHook(({ h }) => useEventQueue(client, h), {
    initialProps: { h: makeHandlers() },
  })
  for (const event of trace) {
    if (event.type === 'rerender') {
      view.rerender({ h: makeHandlers() })
    } else {
      socket().serverMessage(event)
    }
  }
  await vi.runAllTimersAsync()
  view.unmount()
  return state
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket)
  FakeWebSocket.instances = []
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  client = new SimBridgeClient('ws://diff-test', 1000)
  client.connect()
  socket().serverOpen()
})

afterEach(() => {
  client.disconnect()
  for (let i = 0; i < 25 && vi.getTimerCount() > 0; i++) vi.runOnlyPendingTimers()
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe("Jack's exact counterexamples", () => {
  it('CE1: positionless update BEFORE a position-bearing update for an unknown node', async () => {
    // Sequentially the first update is rejected WHOLE (unknown node, no
    // position) — its fields must never resurrect via folding.
    const trace: TraceEvent[] = [
      { type: 'node_update', payload: { id: 'x', status: 'error' } },
      { type: 'node_update', payload: { id: 'x', position: [1, 2, 3] } },
    ]
    const expected = referenceReduce(trace)
    expect(expected.nodes[0].status).toBeUndefined() // the reference itself: no status
    const actual = await queueReduce(trace)
    expect(actual.nodes).toEqual(expected.nodes)
  })

  it('CE2: queued node update BEFORE a partial nodes snapshot must be observed by that snapshot', async () => {
    // Sequentially the update lands first, so the snapshot's positionless
    // entry keeps the freshly updated position. Discarding the queued
    // update makes the snapshot reconcile against stale state.
    const trace: TraceEvent[] = [
      { type: 'node_update', payload: { id: 'a', position: [9, 9, 9], connections: [], status: 'active' } },
      { type: 'network_update', payload: { nodes: [{ id: 'a', status: 'error' }] } },
    ]
    const expected = referenceReduce(trace)
    expect(expected.nodes).toEqual([
      { id: 'a', position: [9, 9, 9], connections: [], status: 'error' },
    ])
    const actual = await queueReduce(trace)
    expect(actual.nodes).toEqual(expected.nodes)
  })
})

describe('generated mixed traces (seeded, thousands of events)', () => {
  // Deterministic LCG; NO Math.random.
  const makeRand = (seed: number) => () =>
    (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648

  function generateTrace(seed: number, length: number): TraceEvent[] {
    const rand = makeRand(seed)
    const ids = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
    const pick = () => ids[Math.floor(rand() * ids.length)]
    const trace: TraceEvent[] = []
    for (let i = 0; i < length; i++) {
      const r = rand()
      if (r < 0.45) {
        // node updates: positionful, positionless, malformed
        const roll = rand()
        trace.push({
          type: 'node_update',
          payload:
            roll < 0.5
              ? { id: pick(), position: [i, Math.floor(rand() * 10), 0], status: rand() < 0.5 ? 'error' : 'active' }
              : roll < 0.8
                ? { id: pick(), status: rand() < 0.5 ? 'error' : 'inactive', connections: rand() < 0.5 ? ['k'] : undefined }
                : { id: pick(), position: 'garbage' },
        })
      } else if (r < 0.62) {
        // full/partial/malformed nodes snapshots
        const entries: unknown[] = []
        const count = Math.floor(rand() * 4)
        for (let k = 0; k < count; k++) {
          const roll = rand()
          entries.push(
            roll < 0.5
              ? { id: pick(), position: [i, k, 1], connections: [], status: 'active' }
              : roll < 0.8
                ? { id: pick(), status: 'error' } // partial: relies on prior state
                : null, // malformed entry
          )
        }
        trace.push({ type: 'network_update', payload: { nodes: entries } })
      } else if (r < 0.75) {
        // edges-only snapshots
        trace.push({
          type: 'network_update',
          payload: { edges: [{ id: `e${Math.floor(rand() * 4)}`, source: pick(), target: pick(), strength: 1 }] },
        })
      } else if (r < 0.85) {
        // combined snapshot
        trace.push({
          type: 'network_update',
          payload: {
            nodes: [{ id: pick(), position: [i, 0, 2], connections: [], status: 'inactive' }],
            edges: [{ id: `e${Math.floor(rand() * 4)}`, source: pick(), target: pick(), strength: 2 }],
          },
        })
      } else if (r < 0.93) {
        trace.push({ type: 'rerender' })
      } else {
        // junk payloads
        trace.push({ type: 'node_update', payload: rand() < 0.5 ? null : 'junk' })
      }
    }
    return trace
  }

  it('every non-overflow trace matches the sequential reference exactly (nodes AND edges)', async () => {
    // 60 traces x 60 events = 3,600 mixed events across all shapes.
    for (let seed = 1; seed <= 60; seed++) {
      const trace = generateTrace(seed * 7919, 60)
      const expected = referenceReduce(trace)
      const actual = await queueReduce(trace)
      expect(actual.nodes, `trace seed ${seed * 7919} nodes`).toEqual(expected.nodes)
      expect(actual.edges, `trace seed ${seed * 7919} edges`).toEqual(expected.edges)
    }
  }, 60000)

  it('subscription count stays exactly one per channel across handler rerenders', async () => {
    const onSpy = vi.spyOn(client, 'on')
    const offSpy = vi.spyOn(client, 'off')
    const trace = generateTrace(31337, 40)
    await queueReduce(trace)
    // One subscription set at mount, one unsubscription set at unmount —
    // rerenders with fresh handler objects add NOTHING.
    expect(onSpy.mock.calls.length).toBe(3)
    expect(offSpy.mock.calls.length).toBe(3)
  })
})
