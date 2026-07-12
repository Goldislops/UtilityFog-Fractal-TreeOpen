// Package AJ (amendment): the shared readiness predicate is itself under
// test. It executes in two hosts — serialized into the page by
// waitForFunction, and directly under jsdom here — so its contract
// (optional chaining everywhere, semantic "active application socket")
// is locked at the pure-function seam both hosts share.
import { describe, it, expect, afterEach } from 'vitest'
import { applicationSocketReady } from '../tests/helpers/waitForApplicationSocket'

type Registry = Array<{ url?: unknown; readyState?: unknown } | undefined>
const install = (registry: Registry | undefined) => {
  ;(window as unknown as { __fakeSockets?: Registry }).__fakeSockets = registry
}
const ready = (minCount = 1, path = '/ws') => applicationSocketReady({ path, minCount })

afterEach(() => {
  delete (window as unknown as { __fakeSockets?: Registry }).__fakeSockets
})

describe('applicationSocketReady', () => {
  it('absent registry (init script not yet installed) is not-ready, never a crash', () => {
    install(undefined)
    expect(ready()).toBe(false)
  })

  it('empty registry (app has not constructed its socket) is not-ready', () => {
    install([])
    expect(ready()).toBe(false)
  })

  it('a registry with only NON-application sockets is not-ready', () => {
    install([{ url: 'ws://localhost:5173/hmr', readyState: 1 }])
    expect(ready()).toBe(false)
  })

  it('a STALE application socket (latest matching entry CLOSED) is not-ready', () => {
    install([{ url: 'ws://localhost/ws', readyState: 3 }])
    expect(ready()).toBe(false)
  })

  it('an active application socket is ready — CONNECTING counts (specs open it themselves)', () => {
    install([{ url: 'ws://localhost/ws', readyState: 0 }])
    expect(ready()).toBe(true)
    install([{ url: 'ws://localhost/ws', readyState: 1 }])
    expect(ready()).toBe(true)
  })

  it('the LATEST matching socket decides: closed-then-reopened is ready, open-then-closed is not', () => {
    install([
      { url: 'ws://localhost/ws', readyState: 3 },
      { url: 'ws://localhost/ws', readyState: 0 },
    ])
    expect(ready()).toBe(true)
    install([
      { url: 'ws://localhost/ws', readyState: 1 },
      { url: 'ws://localhost/ws', readyState: 3 },
    ])
    expect(ready()).toBe(false)
  })

  it('minCount gates reconnect scenarios: one socket does not satisfy minCount 2, two do', () => {
    install([{ url: 'ws://localhost/ws', readyState: 3 }])
    expect(ready(2)).toBe(false)
    install([
      { url: 'ws://localhost/ws', readyState: 3 },
      { url: 'ws://localhost/ws', readyState: 0 },
    ])
    expect(ready(2)).toBe(true)
  })

  it('hostile registry shapes — holes and url-less entries — read as not-matching, never throw', () => {
    install([undefined, { readyState: 1 }, { url: 42, readyState: 1 }])
    expect(ready()).toBe(false)
  })
})
