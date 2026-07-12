// Package W: SimBridgeClient lifecycle contracts, tested directly — no
// browser, no real sockets, no sleeps.
//
// A typed FakeWebSocket replaces the global constructor via vi.stubGlobal
// (auto-restored by unstubGlobals) and vi.useFakeTimers drives every
// scheduled callback deterministically. The fake reproduces the one browser
// behavior the original zombie-reconnect defect depended on: close()
// delivers its onclose callback ASYNCHRONOUSLY (a macrotask), while
// server-driven transitions are synchronous.
//
// Every test ends through the afterEach settlement gate, which itself
// asserts the teardown contract: after disconnect + drained timers there
// are no surviving timers and no zombie sockets.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { SimBridgeClient } from '../src/ws/SimBridgeClient'

const URL = 'ws://unit-test'
const DELAY = 1000

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static instances: FakeWebSocket[] = []
  static failNextConstruction = false
  static reset() {
    FakeWebSocket.instances = []
    FakeWebSocket.failNextConstruction = false
  }

  url: string
  readyState = 0
  sent: string[] = []
  onopen: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: unknown) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null

  constructor(url: string) {
    if (FakeWebSocket.failNextConstruction) {
      FakeWebSocket.failNextConstruction = false
      throw new Error('synthetic construction failure')
    }
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    if (this.readyState === 3) return
    this.readyState = 3
    // Browsers deliver onclose asynchronously after a local close().
    setTimeout(() => {
      this.onclose?.({})
    }, 0)
  }

  // Server-driven transitions (synchronous, like receiving from the wire).
  serverOpen() {
    this.readyState = 1
    this.onopen?.({})
  }
  serverClose() {
    if (this.readyState === 3) return
    this.readyState = 3
    this.onclose?.({})
  }
  serverMessage(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }
  serverMessageRaw(raw: string) {
    this.onmessage?.({ data: raw })
  }
  serverError() {
    this.onerror?.(new Error('socket error'))
  }
}

let client: SimBridgeClient
let events: string[]

const sockets = () => FakeWebSocket.instances
const last = () => {
  const instance = FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
  if (!instance) {
    throw new Error(
      'No fake socket has been constructed yet — call client.connect() before driving socket events.',
    )
  }
  return instance
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket)
  // The client narrates lifecycle transitions on the console; silence the
  // noise while keeping the calls assertable (parse-error channel tests).
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  FakeWebSocket.reset()
  events = []
  client = new SimBridgeClient(URL, DELAY)
  client.on('connected', () => events.push('connected'))
  client.on('disconnected', () => events.push('disconnected'))
  client.on('error', () => events.push('error'))
})

afterEach(() => {
  // Settlement gate: every test must be able to end cleanly. disconnect()
  // cancels reconnect intent; draining timers then advancing far past the
  // reconnect delay must produce NO new sockets and leave NO timers —
  // the teardown contract itself.
  client.disconnect()
  // Bounded drain: run only the timers pending at each step, with a hard
  // iteration cap — a recursive-timer defect fails this assertion loudly
  // instead of hanging the runner the way runAllTimers() could.
  for (let i = 0; i < 25 && vi.getTimerCount() > 0; i++) {
    vi.runOnlyPendingTimers()
  }
  const settled = sockets().length
  vi.advanceTimersByTime(60 * DELAY)
  expect(sockets().length).toBe(settled)
  expect(vi.getTimerCount()).toBe(0)
  FakeWebSocket.reset()
  // Explicit restoration (the config also does this; stating it here makes
  // the isolation contract local and audit-visible).
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('connect', () => {
  it('from idle creates exactly one socket and emits connected once on open', () => {
    expect(sockets()).toHaveLength(0)
    client.connect()
    expect(sockets()).toHaveLength(1)
    expect(sockets()[0].url).toBe(URL)
    expect(events).toEqual([])
    last().serverOpen()
    expect(events).toEqual(['connected'])
    expect(client.isConnected).toBe(true)
  })

  it('is idempotent while CONNECTING: no second socket, no events', () => {
    client.connect()
    client.connect()
    client.connect()
    expect(sockets()).toHaveLength(1)
    expect(events).toEqual([])
  })

  it('is idempotent while OPEN: no second socket, connected emitted exactly once', () => {
    client.connect()
    last().serverOpen()
    client.connect()
    expect(sockets()).toHaveLength(1)
    expect(events).toEqual(['connected'])
  })
})

describe('construction failure', () => {
  it('emits error, schedules exactly one retry, and the retry succeeds', () => {
    FakeWebSocket.failNextConstruction = true
    client.connect()
    expect(sockets()).toHaveLength(0)
    expect(events).toEqual(['error'])
    expect(vi.getTimerCount()).toBe(1)

    vi.advanceTimersByTime(DELAY)
    expect(sockets()).toHaveLength(1)
    last().serverOpen()
    expect(events).toEqual(['error', 'connected'])
  })

  it('does not retry when intent was cancelled before the timer fires', () => {
    FakeWebSocket.failNextConstruction = true
    client.connect()
    client.disconnect()
    vi.advanceTimersByTime(10 * DELAY)
    expect(sockets()).toHaveLength(0)
  })
})

describe('reconnect scheduling', () => {
  it('unexpected close emits disconnected and schedules exactly one reconnect', () => {
    client.connect()
    last().serverOpen()
    last().serverClose()
    expect(events).toEqual(['connected', 'disconnected'])
    expect(vi.getTimerCount()).toBe(1)

    vi.advanceTimersByTime(DELAY)
    expect(sockets()).toHaveLength(2)

    // No second replacement from the same close, ever.
    vi.advanceTimersByTime(10 * DELAY)
    expect(sockets()).toHaveLength(2)
  })

  it('a successful open clears pending reconnect state', () => {
    client.connect()
    last().serverOpen()
    last().serverClose()          // schedules reconnect #1
    vi.advanceTimersByTime(DELAY) // replacement socket created
    last().serverOpen()           // and opens
    vi.advanceTimersByTime(10 * DELAY)
    expect(sockets()).toHaveLength(2)
    expect(events).toEqual(['connected', 'disconnected', 'connected'])
  })

  it('an explicit connect while a reconnect is pending replaces the timer, never doubling sockets', () => {
    client.connect()
    last().serverOpen()
    last().serverClose()          // reconnect pending
    client.connect()              // user reconnects manually first
    expect(sockets()).toHaveLength(2)
    last().serverOpen()
    vi.advanceTimersByTime(10 * DELAY)
    expect(sockets()).toHaveLength(2) // pending timer was cleared, not stacked
  })
})

describe('disconnect', () => {
  it('cancels reconnect intent and any scheduled timer', () => {
    client.connect()
    last().serverOpen()
    last().serverClose()          // schedules reconnect
    expect(vi.getTimerCount()).toBe(1)
    client.disconnect()
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(10 * DELAY)
    expect(sockets()).toHaveLength(1)
  })

  it('emits disconnected synchronously and the socket\'s ASYNC close callback stays inert', () => {
    client.connect()
    last().serverOpen()
    client.disconnect()
    // Synchronous, truthful UI state — before the macrotask lands.
    expect(events).toEqual(['connected', 'disconnected'])
    expect(client.isConnected).toBe(false)

    // The fake delivers the close callback asynchronously, exactly like a
    // browser. Identity was released BEFORE close(), so this must produce
    // no second disconnected and no reconnect.
    vi.runAllTimers()
    expect(events).toEqual(['connected', 'disconnected'])
    expect(sockets()).toHaveLength(1)
  })

  it('a fresh connect after disconnect creates a new working socket', () => {
    client.connect()
    last().serverOpen()
    client.disconnect()
    vi.runAllTimers()
    client.connect()
    expect(sockets()).toHaveLength(2)
    last().serverOpen()
    expect(events).toEqual(['connected', 'disconnected', 'connected'])
    expect(client.isConnected).toBe(true)
  })
})

describe('stale-socket identity', () => {
  it('every callback on an obsolete socket is inert', () => {
    client.connect()
    const stale = last()
    stale.serverOpen()
    stale.serverClose()           // schedules reconnect
    vi.advanceTimersByTime(DELAY) // replacement created
    const current = last()
    current.serverOpen()
    const snapshot = [...events]
    const payloads: unknown[] = []
    client.on('node_update', (p) => payloads.push(p))

    // Fire EVERY callback on the stale socket.
    stale.onopen?.({})
    stale.onmessage?.({ data: JSON.stringify({ type: 'node_update', payload: { id: 'stale' } }) })
    stale.onerror?.(new Error('stale error'))
    stale.onclose?.({})

    expect(events).toEqual(snapshot)
    expect(payloads).toEqual([])
    expect(client.isConnected).toBe(true)
    vi.advanceTimersByTime(10 * DELAY)
    expect(sockets()).toHaveLength(2) // stale close scheduled nothing
  })
})

describe('send', () => {
  it('serializes and sends only while OPEN', () => {
    client.connect()
    client.send({ kind: 'early' })              // CONNECTING: dropped
    expect(last().sent).toEqual([])

    last().serverOpen()
    client.send({ kind: 'live', n: 1 })
    expect(last().sent).toEqual([JSON.stringify({ kind: 'live', n: 1 })])

    const socket = last()
    client.disconnect()
    client.send({ kind: 'late' })               // no socket: dropped
    expect(socket.sent).toHaveLength(1)
  })
})

describe('message routing', () => {
  it('routes each known channel to its listeners with the payload', () => {
    const seen: Array<{ channel: string; payload: unknown }> = []
    for (const ch of ['simulation_event', 'network_update', 'node_update', 'edge_update']) {
      client.on(ch, (p) => seen.push({ channel: ch, payload: p }))
    }
    client.connect()
    last().serverOpen()
    last().serverMessage({ type: 'simulation_event', payload: { kind: 'tick' } })
    last().serverMessage({ type: 'network_update', payload: { nodes: [] } })
    last().serverMessage({ type: 'node_update', payload: { id: 'n1' } })
    last().serverMessage({ type: 'edge_update', payload: { id: 'e1' } })
    expect(seen).toEqual([
      { channel: 'simulation_event', payload: { kind: 'tick' } },
      { channel: 'network_update', payload: { nodes: [] } },
      { channel: 'node_update', payload: { id: 'n1' } },
      { channel: 'edge_update', payload: { id: 'e1' } },
    ])
  })

  it('malformed JSON goes to the parse-error channel and reaches no listener', () => {
    const payloads: unknown[] = []
    client.on('node_update', (p) => payloads.push(p))
    client.connect()
    last().serverOpen()
    expect(() => last().serverMessageRaw('{this is not json')).not.toThrow()
    expect(payloads).toEqual([])
    const errorCalls = vi.mocked(console.error).mock.calls
    expect(errorCalls.some(args => args[0] === 'Error parsing message:')).toBe(true)
  })

  it('a listener exception propagates and is NOT mislabeled as a parse error', () => {
    client.on('node_update', () => {
      throw new Error('listener boom')
    })
    client.connect()
    last().serverOpen()
    expect(() =>
      last().serverMessage({ type: 'node_update', payload: { id: 'n1' } }),
    ).toThrow('listener boom')
    const errorCalls = vi.mocked(console.error).mock.calls
    expect(errorCalls.some(args => args[0] === 'Error parsing message:')).toBe(false)
  })

  it('non-object and unknown-type messages are logged and dropped without listener calls', () => {
    const payloads: unknown[] = []
    client.on('node_update', (p) => payloads.push(p))
    client.connect()
    last().serverOpen()
    last().serverMessageRaw('42')                       // valid JSON, not an object
    last().serverMessageRaw('null')
    last().serverMessage({ type: 'mystery', payload: 1 })
    expect(payloads).toEqual([])
    const logCalls = vi.mocked(console.log).mock.calls
    expect(logCalls.filter(args => args[0] === 'Unknown message type:').length).toBe(3)
  })

  it('socket errors emit on the error channel with the connection intact', () => {
    client.connect()
    last().serverOpen()
    last().serverError()
    expect(events).toEqual(['connected', 'error'])
    expect(client.isConnected).toBe(true)
  })
})

describe('listener registry', () => {
  it('off() unsubscribes exactly the given callback; remaining listeners still fire in order', () => {
    const calls: string[] = []
    const a = () => calls.push('a')
    const b = () => calls.push('b')
    const c = () => calls.push('c')
    client.on('node_update', a)
    client.on('node_update', b)
    client.on('node_update', c)
    client.off('node_update', b)
    client.connect()
    last().serverOpen()
    last().serverMessage({ type: 'node_update', payload: {} })
    expect(calls).toEqual(['a', 'c']) // registration order, minus b

    client.off('node_update', a)
    client.off('node_update', c)
    last().serverMessage({ type: 'node_update', payload: {} })
    expect(calls).toEqual(['a', 'c'])
  })

  it('off() for an unknown listener or channel is a safe no-op', () => {
    expect(() => client.off('node_update', () => {})).not.toThrow()
    expect(() => client.off('never-registered', () => {})).not.toThrow()
  })

  it('the same callback registered on two channels receives both, unsubscribes independently', () => {
    const seen: unknown[] = []
    const cb = (p?: unknown) => seen.push(p)
    client.on('node_update', cb)
    client.on('edge_update', cb)
    client.connect()
    last().serverOpen()
    last().serverMessage({ type: 'node_update', payload: 'n' })
    last().serverMessage({ type: 'edge_update', payload: 'e' })
    expect(seen).toEqual(['n', 'e'])
    client.off('node_update', cb)
    last().serverMessage({ type: 'node_update', payload: 'n2' })
    last().serverMessage({ type: 'edge_update', payload: 'e2' })
    expect(seen).toEqual(['n', 'e', 'e2'])
  })
})

describe('environment discipline', () => {
  it('the global WebSocket in force during tests is the fake (no real network path exists)', () => {
    expect(globalThis.WebSocket).toBe(FakeWebSocket as unknown as typeof WebSocket)
    client.connect()
    expect(last()).toBeInstanceOf(FakeWebSocket)
  })
})
