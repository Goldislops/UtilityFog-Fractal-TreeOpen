// Package AF: the typed backpressure queue — bounded pending work, single
// scheduled drain, snapshot supersession, per-id coalescing, explicit
// overflow.
//
// Driven through the REAL SimBridgeClient against a typed fake WebSocket
// (wire → queue → handler end to end) under fake timers; the async advance
// variants interleave the microtasks the drain loop awaits.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useEventQueue, DEFAULT_MAX_PENDING_WORK } from '../src/viz3d/useEventQueue'
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

let client: SimBridgeClient
let handlers: {
  updateNode: ReturnType<typeof vi.fn<(node: unknown) => void>>
  setNetwork: ReturnType<typeof vi.fn<(nodes: unknown, edges: unknown) => void>>
}

const socket = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
const nodeMsg = (payload: unknown) => socket().serverMessage({ type: 'node_update', payload })
const netMsg = (payload: unknown) => socket().serverMessage({ type: 'network_update', payload })
const NODE = (id: string, extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  id,
  position: [1, 2, 3],
  connections: [],
  status: 'active',
  ...extra,
})

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket)
  FakeWebSocket.instances = []
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  client = new SimBridgeClient('ws://queue-test', 1000)
  client.connect()
  socket().serverOpen()
  handlers = {
    updateNode: vi.fn<(node: unknown) => void>(),
    setNetwork: vi.fn<(nodes: unknown, edges: unknown) => void>(),
  }
})

afterEach(() => {
  client.disconnect()
  for (let i = 0; i < 25 && vi.getTimerCount() > 0; i++) {
    vi.runOnlyPendingTimers()
  }
  expect(vi.getTimerCount()).toBe(0)
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('single scheduled drain', () => {
  it('many synchronous enqueues schedule EXACTLY ONE animation frame', async () => {
    renderHook(() => useEventQueue(client, handlers))
    const rafSpy = vi.spyOn(globalThis, 'requestAnimationFrame')
    for (let i = 0; i < 15; i++) nodeMsg(NODE(`n${i}`))
    expect(rafSpy).toHaveBeenCalledTimes(1) // the old closure queue scheduled 15
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(15)
  })

  it('a drain over multiple batches yields one continuation frame at a time', async () => {
    renderHook(() => useEventQueue(client, handlers))
    const rafSpy = vi.spyOn(globalThis, 'requestAnimationFrame')
    for (let i = 0; i < 120; i++) nodeMsg(NODE(`n${i}`)) // 3 batches of 50
    expect(rafSpy).toHaveBeenCalledTimes(1)
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(120)
    // 1 schedule + 2 continuation yields (120 items / 50 per frame).
    expect(rafSpy).toHaveBeenCalledTimes(3)
  })
})

describe('coalescing and ordering', () => {
  it('repeated updates for one id deliver once, latest-valid-wins per field', async () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    nodeMsg({ id: 'n1', position: [1, 1, 1], status: 'active' })
    nodeMsg({ id: 'n1', status: 'error' })                    // no position: keeps [1,1,1]
    nodeMsg({ id: 'n1', position: 'garbage' })                // invalid: keeps [1,1,1]
    nodeMsg({ id: 'n1', position: [9, 9, 9] })                // latest valid position
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(1)
    expect(handlers.updateNode).toHaveBeenCalledWith({
      id: 'n1',
      position: [9, 9, 9],
      status: 'error',
    })
    expect(view.result.current.stats.coalesced).toBe(3)
  })

  it('distinct ids preserve insertion order', async () => {
    renderHook(() => useEventQueue(client, handlers))
    for (const id of ['a', 'b', 'c', 'd']) nodeMsg(NODE(id))
    await vi.runAllTimersAsync()
    expect(handlers.updateNode.mock.calls.map(args => (args[0] as { id: string }).id)).toEqual([
      'a',
      'b',
      'c',
      'd',
    ])
  })

  it('invalid/unidentifiable payloads are counted and never enter the queue', async () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    nodeMsg(null)
    nodeMsg('junk')
    nodeMsg({ status: 'active' })              // no id
    nodeMsg({ id: '', position: [1, 2, 3] })   // empty id
    expect(view.result.current.pendingCount()).toBe(0)
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).not.toHaveBeenCalled()
    expect(view.result.current.stats.invalidDropped).toBe(4)
  })
})

describe('snapshot barriers (audit redesign)', () => {
  it('a nodes-carrying snapshot PRESERVES earlier queued node updates, in order', async () => {
    renderHook(() => useEventQueue(client, handlers))
    nodeMsg(NODE('pre1'))
    nodeMsg(NODE('pre2'))
    netMsg({ nodes: [NODE('snap')], edges: [] })
    nodeMsg(NODE('post1'))
    await vi.runAllTimersAsync()

    // Barrier ordering: pre-updates deliver BEFORE the snapshot, post-
    // updates after — nothing is discarded.
    expect(handlers.updateNode).toHaveBeenCalledTimes(3)
    expect(handlers.setNetwork).toHaveBeenCalledTimes(1)
    const preOrders = handlers.updateNode.mock.invocationCallOrder.slice(0, 2)
    const snapOrder = handlers.setNetwork.mock.invocationCallOrder[0]
    const postOrder = handlers.updateNode.mock.invocationCallOrder[2]
    expect(Math.max(...preOrders)).toBeLessThan(snapOrder)
    expect(snapOrder).toBeLessThan(postOrder)
  })

  it('updates never fold ACROSS a barrier — same id before and after stays two deliveries', async () => {
    renderHook(() => useEventQueue(client, handlers))
    nodeMsg({ id: 'x', position: [1, 1, 1] })
    netMsg({ nodes: [] })
    nodeMsg({ id: 'x', position: [2, 2, 2] })
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(2)
    expect(handlers.updateNode).toHaveBeenNthCalledWith(1, { id: 'x', position: [1, 1, 1] })
    expect(handlers.updateNode).toHaveBeenNthCalledWith(2, { id: 'x', position: [2, 2, 2] })
  })

  it('consecutive snapshots stay ordered as separate deliveries (never merged)', async () => {
    renderHook(() => useEventQueue(client, handlers))
    netMsg({ nodes: [NODE('n1')], edges: [{ id: 'e1', source: 'a', target: 'b' }] })
    netMsg({ nodes: [NODE('n2')] })
    await vi.runAllTimersAsync()
    expect(handlers.setNetwork).toHaveBeenCalledTimes(2)
    expect((handlers.setNetwork.mock.calls[0][0] as Array<{ id: string }>)[0].id).toBe('n1')
    expect((handlers.setNetwork.mock.calls[1][0] as Array<{ id: string }>)[0].id).toBe('n2')
    expect(handlers.setNetwork.mock.calls[1][1]).toBeUndefined()
  })

  it('the positionless->positionful transition stays two ordered candidates (CE1 mechanism)', async () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    nodeMsg({ id: 'x', status: 'error' })            // positionless: not folded forward
    nodeMsg({ id: 'x', position: [1, 2, 3] })        // anchored: new candidate
    nodeMsg({ id: 'x', status: 'inactive' })         // folds into the anchored one
    expect(view.result.current.pendingCount()).toBe(2)
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(2)
    expect(handlers.updateNode).toHaveBeenNthCalledWith(1, { id: 'x', status: 'error' })
    expect(handlers.updateNode).toHaveBeenNthCalledWith(2, {
      id: 'x',
      position: [1, 2, 3],
      status: 'inactive',
    })
    expect(view.result.current.stats.coalesced).toBe(1)
  })

  it('null/primitive/empty network payloads enqueue nothing', async () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    netMsg(null)
    netMsg('junk')
    netMsg({})
    expect(view.result.current.pendingCount()).toBe(0)
    await vi.runAllTimersAsync()
    expect(handlers.setNetwork).not.toHaveBeenCalled()
  })
})

describe('overflow boundary', () => {
  it('exact limit fills; limit+1 NEW id drops with an accurate counter; folds still proceed', async () => {
    const view = renderHook(() =>
      useEventQueue(client, handlers, { maxPendingWork: 3 }),
    )
    nodeMsg(NODE('a'))
    nodeMsg(NODE('b'))
    nodeMsg(NODE('c'))          // exactly at limit: all admitted
    expect(view.result.current.pendingCount()).toBe(3)
    expect(view.result.current.stats.dropped).toBe(0)

    nodeMsg(NODE('d'))          // limit+1: new id dropped
    expect(view.result.current.stats.dropped).toBe(1)
    nodeMsg({ id: 'b', status: 'error' }) // fold into pending id: allowed during overflow
    expect(view.result.current.stats.coalesced).toBe(1)
    expect(view.result.current.pendingCount()).toBe(3)

    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(3)
    expect(handlers.updateNode.mock.calls.map(args => (args[0] as { id: string }).id)).toEqual([
      'a',
      'b',
      'c',
    ])
  })

  it('one bounded diagnostic per overflow episode — no console spam', async () => {
    renderHook(() => useEventQueue(client, handlers, { maxPendingWork: 2 }))
    nodeMsg(NODE('a'))
    nodeMsg(NODE('b'))
    nodeMsg(NODE('c'))
    nodeMsg(NODE('d'))
    nodeMsg(NODE('e'))
    const overflowReports = () =>
      vi.mocked(console.error).mock.calls.filter(args =>
        String(args[0]).startsWith('Event queue overflow'),
      )
    expect(overflowReports()).toHaveLength(1) // three drops, one episode report

    await vi.runAllTimersAsync() // queue drains: episode ends
    nodeMsg(NODE('f'))
    nodeMsg(NODE('g'))
    nodeMsg(NODE('h'))
    expect(overflowReports()).toHaveLength(2) // new episode, one new report
  })

  it('snapshots occupy the same finite bound — no barrier evades accounting — and overflow stays explicitly lossy', async () => {
    const view = renderHook(() => useEventQueue(client, handlers, { maxPendingWork: 2 }))
    netMsg({ nodes: [] })
    netMsg({ nodes: [] }) // the bound filled ENTIRELY by snapshots
    expect(view.result.current.pendingCount()).toBe(2)

    netMsg({ nodes: [] }) // a further snapshot is dropped, not privileged
    nodeMsg(NODE('a')) //    and so is a new node item
    expect(view.result.current.stats.dropped).toBe(2)
    expect(view.result.current.pendingCount()).toBe(2)
    const report = vi
      .mocked(console.error)
      .mock.calls.find(args => String(args[0]).startsWith('Event queue overflow'))
    expect(String(report?.[0])).toContain('NOT lossless')

    await vi.runAllTimersAsync()
    expect(handlers.setNetwork).toHaveBeenCalledTimes(2)
    expect(handlers.updateNode).not.toHaveBeenCalled()
  })

  it('the documented default limit is in force when no injection is provided', () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    expect(DEFAULT_MAX_PENDING_WORK).toBe(5000)
    expect(view.result.current.stats.dropped).toBe(0)
  })
})

describe('100,000-event deterministic burst', () => {
  it('bounded memory, coalesced counters, latest state per id, single-drain discipline', async () => {
    const view = renderHook(() =>
      useEventQueue(client, handlers, { maxPendingWork: 1000 }),
    )
    const rafSpy = vi.spyOn(globalThis, 'requestAnimationFrame')
    const IDS = 500
    const ROUNDS = 200 // 500 ids × 200 rounds = 100,000 events
    for (let round = 0; round < ROUNDS; round++) {
      for (let i = 0; i < IDS; i++) {
        nodeMsg({ id: `n${i}`, position: [round, i, 0], status: 'active' })
      }
    }
    // Pending work stayed bounded by id cardinality, far under the limit.
    expect(view.result.current.pendingCount()).toBe(IDS)
    expect(view.result.current.stats.coalesced).toBe(IDS * (ROUNDS - 1))
    expect(view.result.current.stats.dropped).toBe(0)
    expect(rafSpy).toHaveBeenCalledTimes(1) // one scheduled drain for the whole burst

    await vi.runAllTimersAsync()
    // Exactly one delivery per id, carrying the LATEST round's position.
    expect(handlers.updateNode).toHaveBeenCalledTimes(IDS)
    const delivered = new Map(
      handlers.updateNode.mock.calls.map(args => {
        const p = args[0] as { id: string; position: [number, number, number] }
        return [p.id, p.position] as const
      }),
    )
    expect(delivered.get('n0')).toEqual([ROUNDS - 1, 0, 0])
    expect(delivered.get(`n${IDS - 1}`)).toEqual([ROUNDS - 1, IDS - 1, 0])
    // No retry/infinite loop: the queue is empty and no frame is pending.
    expect(view.result.current.pendingCount()).toBe(0)
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('equivalence against sequential application (non-overflowing traffic)', () => {
  it('the queued final state equals the old sequential semantics on a mixed deterministic trace', async () => {
    // Reference: the exact state sequential application (the old closure
    // queue's semantics) produces, computed with the same pure validators.
    let refNodes: NetworkNode[] = []
    let refEdges: NetworkEdge[] = []
    const referenceApply = (event: { type: string; payload: unknown }) => {
      if (event.type === 'node_update') {
        refNodes = applyNodeUpdate(refNodes, event.payload)
      } else {
        const d = event.payload as { nodes?: unknown; edges?: unknown }
        if (d.nodes !== undefined && Array.isArray(d.nodes)) refNodes = sanitizeNodeList(d.nodes, refNodes)
        refEdges = sanitizeEdgeList(d.edges, refEdges)
      }
    }
    // Queue path drives the SAME validators through the handler seam.
    let qNodes: NetworkNode[] = []
    let qEdges: NetworkEdge[] = []
    handlers.updateNode.mockImplementation((p: unknown) => {
      qNodes = applyNodeUpdate(qNodes, p)
    })
    handlers.setNetwork.mockImplementation((nodes: unknown, edges: unknown) => {
      if (Array.isArray(nodes)) qNodes = sanitizeNodeList(nodes, qNodes)
      qEdges = sanitizeEdgeList(edges, qEdges)
    })
    renderHook(() => useEventQueue(client, handlers))

    // Deterministic mixed trace: interleaved valid/partial/invalid updates
    // and per-side snapshots (seeded LCG — no Math.random).
    let seed = 42
    const rand = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648
    const trace: Array<{ type: string; payload: unknown }> = []
    for (let i = 0; i < 400; i++) {
      const r = rand()
      if (r < 0.6) {
        trace.push({
          type: 'node_update',
          payload:
            rand() < 0.8
              ? { id: `n${Math.floor(rand() * 20)}`, position: [i, rand(), 0], status: rand() < 0.5 ? 'error' : 'active' }
              : { id: `n${Math.floor(rand() * 20)}`, position: 'garbage' },
        })
      } else if (r < 0.8) {
        trace.push({
          type: 'network_update',
          payload: { nodes: [NODE(`snap${Math.floor(rand() * 5)}`, { position: [i, 0, 0] })] },
        })
      } else {
        trace.push({
          type: 'network_update',
          payload: { edges: [{ id: `e${Math.floor(rand() * 5)}`, source: 'a', target: 'b', strength: 1 }] },
        })
      }
    }
    for (const event of trace) {
      referenceApply(event)
      socket().serverMessage(event)
    }
    await vi.runAllTimersAsync()
    expect(qNodes).toEqual(refNodes)
    expect(qEdges).toEqual(refEdges)
  })
})

describe('lifecycle and failure', () => {
  it('unmount clears queued work and schedules no further frames', async () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    for (let i = 0; i < 5; i++) nodeMsg(NODE(`n${i}`))
    expect(view.result.current.pendingCount()).toBe(5)
    view.unmount()
    expect(view.result.current.pendingCount()).toBe(0)
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).not.toHaveBeenCalled()
  })

  it('an unmount performed BY a handler stops the remaining batch and requests no extra frame', async () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    const rafSpy = vi.spyOn(globalThis, 'requestAnimationFrame')
    handlers.updateNode.mockImplementationOnce(() => {
      view.unmount()
    })
    nodeMsg(NODE('a'))
    nodeMsg(NODE('b'))
    nodeMsg(NODE('c'))
    expect(rafSpy).toHaveBeenCalledTimes(1)
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(1)
    expect(rafSpy).toHaveBeenCalledTimes(1)
  })

  it('a throwing handler is contained, reported once, and never locks later processing', async () => {
    renderHook(() => useEventQueue(client, handlers))
    handlers.updateNode.mockImplementationOnce(() => {
      throw new Error('handler boom')
    })
    nodeMsg(NODE('a'))
    nodeMsg(NODE('b'))
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(2) // batch-mate survived
    nodeMsg(NODE('c'))
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(3) // queue not locked
    const reports = vi.mocked(console.error).mock.calls.filter(
      args => args[0] === 'Event handler failed:',
    )
    expect(reports).toHaveLength(1)
  })

  it('a throwing setNetwork handler is equally contained', async () => {
    renderHook(() => useEventQueue(client, handlers))
    handlers.setNetwork.mockImplementationOnce(() => {
      throw new Error('snapshot boom')
    })
    netMsg({ nodes: [NODE('s')] })
    nodeMsg(NODE('after'))
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(1)
  })

  it('subscribes once per channel; identical rerenders do not resubscribe; unmount detaches', () => {
    const onSpy = vi.spyOn(client, 'on')
    const offSpy = vi.spyOn(client, 'off')
    const view = renderHook(() => useEventQueue(client, handlers))
    expect(onSpy.mock.calls.length).toBe(3)
    view.rerender()
    expect(onSpy.mock.calls.length).toBe(3)
    view.unmount()
    expect(offSpy.mock.calls.length).toBe(3)
  })

  it('a null client subscribes to nothing', async () => {
    renderHook(() => useEventQueue(null, handlers))
    nodeMsg(NODE('n'))
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).not.toHaveBeenCalled()
  })
})

describe('diagnostic surface', () => {
  it('edge_update events are logged through the existing channel (no queue effect)', async () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    socket().serverMessage({ type: 'edge_update', payload: { id: 'e1' } })
    expect(view.result.current.pendingCount()).toBe(0)
    const logs = vi.mocked(console.log).mock.calls.filter(args => args[0] === 'Edge update:')
    expect(logs).toHaveLength(1)
  })

  it('isProcessing reflects the drain lifecycle', async () => {
    const view = renderHook(() => useEventQueue(client, handlers))
    expect(view.result.current.isProcessing()).toBe(false)
    handlers.updateNode.mockImplementationOnce(() => {
      expect(view.result.current.isProcessing()).toBe(true) // observed mid-drain
    })
    nodeMsg(NODE('n'))
    await vi.runAllTimersAsync()
    expect(view.result.current.isProcessing()).toBe(false)
  })
})
