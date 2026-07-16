// Package AF (audit redesign + amendment): DIFFERENTIAL testing — for
// every non-overflowing trace, the queue-delivered final store state must
// equal a plain sequential reference reducer built from the same
// validators the store uses. Includes the two exact counterexamples from
// Jack's audit, 500 fixed-seed generated traces (overflow disabled: no
// trace approaches the 5,000-item default bound, so equality must be
// exact with zero drops), ordered-DELIVERY assertions (not merely
// final-state equality), and the commit-synchronous handler-refresh
// proof.
import { useLayoutEffect } from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, renderHook } from '@testing-library/react'
import { useEventQueue } from '../src/viz3d/useEventQueue'
import { SimBridgeClient } from '../src/ws/SimBridgeClient'
import {
  applyNodeUpdate,
  isValidPosition,
  readNodeUpdate,
  sanitizeNodeList,
} from '../src/viz3d/nodeValidation'
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

// Every handler invocation, in delivery order — the ordered-delivery
// assertions consume this alongside the final state.
type Delivery = { kind: 'node'; id: string; hasPosition: boolean } | { kind: 'snapshot' }

// Drive one trace through the real queue against real-validator handlers;
// rerender events swap in FRESH handler objects that keep writing to the
// same state (proving no subscription gap and newest-handler delivery).
async function queueReduce(trace: TraceEvent[]) {
  const state = {
    nodes: [] as NetworkNode[],
    edges: [] as NetworkEdge[],
    deliveries: [] as Delivery[],
  }
  const makeHandlers = () => ({
    updateNode: (p: unknown) => {
      const rec = p as { id: string; position?: unknown }
      state.deliveries.push({ kind: 'node', id: rec.id, hasPosition: isValidPosition(rec.position) })
      state.nodes = applyNodeUpdate(state.nodes, p)
    },
    setNetwork: (nodes: unknown, edges: unknown) => {
      state.deliveries.push({ kind: 'snapshot' })
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
      if (r < 0.42) {
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
      } else if (r < 0.56) {
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
      } else if (r < 0.63) {
        // POSITIONLESS BARRIER: a snapshot whose every entry is a
        // positionless partial — it contributes nothing without the state
        // produced by the work queued BEFORE it, so any queue that
        // discards or reorders around barriers diverges here.
        trace.push({
          type: 'network_update',
          payload: {
            nodes: [
              { id: pick(), status: 'error' },
              { id: pick(), status: 'inactive' },
            ],
          },
        })
      } else if (r < 0.74) {
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

  // 500 traces × 60 events = 30,000 mixed events across all shapes
  // (chunked so a divergence names its hundred immediately). No trace
  // approaches the 5,000-item bound: overflow is disabled for
  // equivalence, so drops are impossible and equality must be exact.
  for (const chunk of [0, 1, 2, 3, 4]) {
    it(`traces ${chunk * 100 + 1}–${(chunk + 1) * 100} match the sequential reference exactly (nodes AND edges)`, async () => {
      for (let seed = chunk * 100 + 1; seed <= (chunk + 1) * 100; seed++) {
        const trace = generateTrace(seed * 7919, 60)
        const expected = referenceReduce(trace)
        const actual = await queueReduce(trace)
        expect(actual.nodes, `trace seed ${seed * 7919} nodes`).toEqual(expected.nodes)
        expect(actual.edges, `trace seed ${seed * 7919} edges`).toEqual(expected.edges)
      }
    }, 120000)
  }

  it('ordered-delivery invariants hold on generated traces (segment residency, ≤2 deliveries/id/segment, positionless-before-anchored)', async () => {
    for (let seed = 1; seed <= 100; seed++) {
      // Mirror arrival segments through the SAME reader the queue uses:
      // barriers are the valid-shaped snapshots, and a node id belongs to
      // the segment its candidate arrived in.
      const trace = generateTrace(seed * 104729, 60)
      const arrivals: Array<Set<string>> = [new Set()]
      for (const event of trace) {
        if (event.type === 'rerender') continue
        if (event.type === 'network_update') {
          const d = event.payload as { nodes?: unknown; edges?: unknown } | null
          if (!d || typeof d !== 'object') continue
          if (d.nodes === undefined && d.edges === undefined) continue
          arrivals.push(new Set())
        } else {
          const c = readNodeUpdate(event.payload)
          if (c !== null) arrivals[arrivals.length - 1].add(c.id)
        }
      }
      const { deliveries } = await queueReduce(trace)
      let seg = 0
      const perId = new Map<string, { count: number; sawAnchored: boolean }>()
      for (const d of deliveries) {
        if (d.kind === 'snapshot') {
          seg++
          perId.clear()
          continue
        }
        expect(arrivals[seg].has(d.id), `seed ${seed * 104729}: id ${d.id} delivered outside its arrival segment ${seg}`).toBe(true)
        const entry = perId.get(d.id) ?? { count: 0, sawAnchored: false }
        entry.count++
        expect(entry.count, `seed ${seed * 104729}: >2 deliveries for ${d.id} in one segment`).toBeLessThanOrEqual(2)
        if (entry.count === 2) {
          // A second delivery exists ONLY for the unsafe-fold split:
          // positionless first, position-bearing second (audit CE1).
          expect(entry.sawAnchored, `seed ${seed * 104729}: second delivery for ${d.id} after an anchored first`).toBe(false)
          expect(d.hasPosition, `seed ${seed * 104729}: second delivery for ${d.id} is not position-bearing`).toBe(true)
        }
        entry.sawAnchored = entry.sawAnchored || d.hasPosition
        perId.set(d.id, entry)
      }
      // Every arrived barrier was delivered — none skipped or merged.
      expect(seg, `seed ${seed * 104729}: barrier deliveries`).toBe(arrivals.length - 1)
    }
  }, 120000)

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

describe('exact ordered delivery (a trace of calls, not merely final state)', () => {
  it('delivers segment slots in arrival order: folds land in the anchor slot, barriers hold their place, post-barrier work follows', async () => {
    const calls: Array<{ fn: 'updateNode' | 'setNetwork'; arg: unknown }> = []
    const handlers = {
      updateNode: (p: unknown) => calls.push({ fn: 'updateNode', arg: p }),
      setNetwork: (nodes: unknown) => calls.push({ fn: 'setNetwork', arg: nodes }),
    }
    const view = renderHook(() => useEventQueue(client, handlers))
    socket().serverMessage({ type: 'node_update', payload: { id: 'a', position: [1, 1, 1] } })
    socket().serverMessage({ type: 'node_update', payload: { id: 'b', position: [2, 2, 2] } })
    // Folds into a's ANCHOR slot (slot 1), not into a new tail slot.
    socket().serverMessage({ type: 'node_update', payload: { id: 'a', status: 'error' } })
    socket().serverMessage({
      type: 'network_update',
      payload: { nodes: [{ id: 'c', position: [3, 3, 3], connections: [], status: 'active' }] },
    })
    // A fresh segment AFTER the barrier — must deliver last.
    socket().serverMessage({ type: 'node_update', payload: { id: 'a', position: [4, 4, 4] } })
    await vi.runAllTimersAsync()
    expect(calls.map(c => c.fn)).toEqual(['updateNode', 'updateNode', 'setNetwork', 'updateNode'])
    expect(calls[0].arg).toMatchObject({ id: 'a', position: [1, 1, 1], status: 'error' })
    expect(calls[1].arg).toMatchObject({ id: 'b', position: [2, 2, 2] })
    expect(calls[3].arg).toMatchObject({ id: 'a', position: [4, 4, 4] })
    view.unmount()
  })
})

describe('commit-synchronous handler refresh (useLayoutEffect)', () => {
  it('a paint-aligned drain firing between a committed rerender and its passive effects reaches the NEW handlers', async () => {
    // Run rAF callbacks SYNCHRONOUSLY at schedule time: this simulates
    // the browser interleaving a paint-aligned drain into the window
    // between a commit and its passive-effect flush. A passive-effect
    // (useEffect) handler refresh observably delivers to the PREVIOUS
    // generation in exactly this window — verified failing-first against
    // the useEffect implementation; the layout-phase refresh closes it.
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 0
    })
    const received: string[] = []
    const makeHandlers = (generation: string) => ({
      updateNode: () => received.push(generation),
      setNetwork: () => received.push(generation),
    })
    function Harness({ generation }: { generation: string }) {
      useEventQueue(client, makeHandlers(generation))
      // Declared AFTER the hook call: by the time this layout effect
      // emits, the queue's own layout effect in the SAME commit has
      // already refreshed the handler ref (in-component declaration
      // order) — the emission is the very first thing that can happen
      // after the commit, before any passive effect.
      useLayoutEffect(() => {
        if (generation === 'second') {
          socket().serverMessage({ type: 'node_update', payload: { id: 'k', position: [1, 2, 3] } })
        }
      }, [generation])
      return null
    }
    const view = render(<Harness generation="first" />)
    view.rerender(<Harness generation="second" />)
    expect(received).toEqual(['second'])
    await vi.runAllTimersAsync()
    expect(received).toEqual(['second'])
    view.unmount()
  })
})
