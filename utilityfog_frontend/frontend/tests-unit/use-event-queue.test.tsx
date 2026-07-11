// Package X: useEventQueue hook contracts — subscription identity, cleanup,
// rAF batching, and the no-update-after-unmount guarantee.
//
// The hook is driven through the REAL SimBridgeClient against a typed fake
// WebSocket, so wire → queue → handler is exercised end to end. Fake timers
// make the rAF pipeline fully deterministic (the async advance variants
// interleave the microtasks the processing loop awaits).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useEventQueue } from '../src/viz3d/useEventQueue'
import { SimBridgeClient } from '../src/ws/SimBridgeClient'

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

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket)
  FakeWebSocket.instances = []
  vi.spyOn(console, 'log').mockImplementation(() => {})
  client = new SimBridgeClient('ws://hook-test', 1000)
  client.connect()
  socket().serverOpen()
  handlers = {
    updateNode: vi.fn<(node: unknown) => void>(),
    setNetwork: vi.fn<(nodes: unknown, edges: unknown) => void>(),
  }
})

afterEach(() => {
  client.disconnect()
  vi.runAllTimers()
  expect(vi.getTimerCount()).toBe(0)
  FakeWebSocket.instances = []
  vi.useRealTimers()
})

describe('useEventQueue subscriptions', () => {
  it('subscribes once per channel; rerenders with identical inputs do not resubscribe', () => {
    const onSpy = vi.spyOn(client, 'on')
    const { rerender } = renderHook(() => useEventQueue(client, handlers))
    const initialCalls = onSpy.mock.calls.length
    expect(initialCalls).toBe(3) // network_update, node_update, edge_update

    rerender()
    rerender()
    expect(onSpy.mock.calls.length).toBe(initialCalls) // listener identity stable
  })

  it('unsubscribes the SAME handler references on unmount', () => {
    const onSpy = vi.spyOn(client, 'on')
    const offSpy = vi.spyOn(client, 'off')
    const { unmount } = renderHook(() => useEventQueue(client, handlers))
    unmount()
    expect(offSpy.mock.calls.length).toBe(3)
    // Every off() must pass exactly the function that on() registered.
    for (const [channel, handler] of offSpy.mock.calls) {
      expect(onSpy.mock.calls.some(([ch, h]) => ch === channel && h === handler)).toBe(true)
    }
  })

  it('a null client subscribes to nothing', () => {
    renderHook(() => useEventQueue(null, handlers))
    socket().serverMessage({ type: 'node_update', payload: { id: 'n' } })
    vi.runAllTimers()
    expect(handlers.updateNode).not.toHaveBeenCalled()
  })
})

describe('useEventQueue delivery', () => {
  it('delivers node_update payloads to updateNode through the rAF batch', async () => {
    renderHook(() => useEventQueue(client, handlers))
    socket().serverMessage({ type: 'node_update', payload: { id: 'n1' } })
    expect(handlers.updateNode).not.toHaveBeenCalled() // queued, not synchronous
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(1)
    expect(handlers.updateNode).toHaveBeenCalledWith({ id: 'n1' })
  })

  it('forwards network_update sides as-received (store owns per-side validation)', async () => {
    renderHook(() => useEventQueue(client, handlers))
    socket().serverMessage({ type: 'network_update', payload: { nodes: [], edges: [{ id: 'e' }] } })
    socket().serverMessage({ type: 'network_update', payload: { nodes: [] } }) // one side absent
    await vi.runAllTimersAsync()
    expect(handlers.setNetwork).toHaveBeenCalledTimes(2)
    expect(handlers.setNetwork).toHaveBeenNthCalledWith(1, [], [{ id: 'e' }])
    expect(handlers.setNetwork).toHaveBeenNthCalledWith(2, [], undefined)
  })

  it.each([
    { label: 'null payload', payload: null },
    { label: 'string payload', payload: 'junk' },
    { label: 'numeric payload', payload: 7 },
    { label: 'empty object (no nodes/edges keys)', payload: {} },
  ])('network_update with $label enqueues nothing', async ({ payload }) => {
    renderHook(() => useEventQueue(client, handlers))
    socket().serverMessage({ type: 'network_update', payload })
    await vi.runAllTimersAsync()
    expect(handlers.setNetwork).not.toHaveBeenCalled()
  })

  it('node_update payloads pass through opaquely — null and hostile shapes reach the validating store', async () => {
    renderHook(() => useEventQueue(client, handlers))
    socket().serverMessage({ type: 'node_update', payload: null })
    socket().serverMessage({ type: 'node_update', payload: 'not-a-node' })
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(2)
    expect(handlers.updateNode).toHaveBeenNthCalledWith(1, null)
    expect(handlers.updateNode).toHaveBeenNthCalledWith(2, 'not-a-node')
  })

  it('processes a burst in batches, preserving order', async () => {
    renderHook(() => useEventQueue(client, handlers))
    for (let i = 1; i <= 25; i++) {
      socket().serverMessage({ type: 'node_update', payload: { seq: i } })
    }
    await vi.runAllTimersAsync()
    expect(handlers.updateNode).toHaveBeenCalledTimes(25)
    expect(handlers.updateNode.mock.calls.map(args => (args[0] as { seq: number }).seq)).toEqual(
      Array.from({ length: 25 }, (_, i) => i + 1),
    )
  })
})

describe('useEventQueue unmount safety', () => {
  it('queued rAF work cannot invoke handlers after unmount', async () => {
    const { unmount } = renderHook(() => useEventQueue(client, handlers))
    // Enqueue while mounted — the rAF that will process it is now pending.
    socket().serverMessage({ type: 'node_update', payload: { id: 'late' } })
    expect(handlers.updateNode).not.toHaveBeenCalled()

    unmount()
    await vi.runAllTimersAsync() // the pending rAF fires after unmount
    expect(handlers.updateNode).not.toHaveBeenCalled()
    expect(handlers.setNetwork).not.toHaveBeenCalled()
  })

  it('a queue mid-processing stops at the unmount boundary', async () => {
    const { unmount } = renderHook(() => useEventQueue(client, handlers))
    // Two batches' worth: the loop must yield to rAF between batches of 10.
    for (let i = 1; i <= 15; i++) {
      socket().serverMessage({ type: 'node_update', payload: { seq: i } })
    }
    // Fire ONLY the first pending rAF: batch 1 (10 items) processes, then
    // the loop awaits the next frame.
    await vi.advanceTimersByTimeAsync(20)
    expect(handlers.updateNode.mock.calls.length).toBeGreaterThanOrEqual(10)
    const deliveredBeforeUnmount = handlers.updateNode.mock.calls.length

    unmount()
    await vi.runAllTimersAsync()
    expect(handlers.updateNode.mock.calls.length).toBe(deliveredBeforeUnmount)
  })
})
