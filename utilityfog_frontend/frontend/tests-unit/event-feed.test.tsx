// Package X: EventFeed contracts — meaningful behavior, no snapshots.
//
// The component consumes only the on/off surface of SimBridgeClient, so a
// typed stub provides it (the cast below is unknown-mediated at the test
// boundary; the class's private fields make structural assignment
// impossible, and no `as any` is used). Emissions are wrapped in act()
// because they drive React state.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode } from 'react'
import { render, screen, within, act, fireEvent } from '@testing-library/react'
import EventFeed from '../src/components/EventFeed'
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
  countFor(event: string) {
    return this.listeners.get(event)?.size ?? 0
  }
  totalListeners() {
    let n = 0
    this.listeners.forEach(set => (n += set.size))
    return n
  }
}

let stub: StubSimClient
const asClient = () => stub as unknown as SimBridgeClient

const log = () => screen.getByRole('log', { name: 'Event feed' })
const entries = () => Array.from(log().querySelectorAll('[data-event-channel]'))
const summary = () => screen.getByTestId('feed-summary')

const emit = (channel: string, payload?: unknown) => {
  act(() => stub.emit(channel, payload))
}

beforeEach(() => {
  stub = new StubSimClient()
})

describe('EventFeed subscription lifecycle', () => {
  it('subscribes exactly once per channel and unsubscribes all on unmount', () => {
    const { unmount } = render(<EventFeed simClient={asClient()} />)
    for (const ch of ['simulation_event', 'network_update', 'node_update', 'edge_update']) {
      expect(stub.countFor(ch)).toBe(1)
    }
    unmount()
    expect(stub.totalListeners()).toBe(0)
  })

  it('StrictMode double-mount leaves exactly one subscription per channel and no duplicate entries', () => {
    render(
      <StrictMode>
        <EventFeed simClient={asClient()} />
      </StrictMode>,
    )
    for (const ch of ['simulation_event', 'network_update', 'node_update', 'edge_update']) {
      expect(stub.countFor(ch)).toBe(1)
    }
    emit('node_update', { id: 'once' })
    expect(entries()).toHaveLength(1)
  })

  it('renders the empty state without a client', () => {
    render(<EventFeed simClient={null} />)
    expect(summary()).toHaveTextContent('No events retained.')
    expect(log()).toHaveTextContent('No events yet...')
  })
})

describe('EventFeed rendering contracts', () => {
  beforeEach(() => {
    render(<EventFeed simClient={asClient()} />)
  })

  it('channel label comes from the subscription, never from a payload `type` field', () => {
    emit('node_update', { type: 'edge_update', id: 'spoof' })
    const [entry] = entries()
    expect(entry).toHaveAttribute('data-event-channel', 'node_update')
    expect(within(entry as HTMLElement).getByText('node_update')).toBeInTheDocument()
    expect(within(entry as HTMLElement).queryByText('edge_update')).not.toBeInTheDocument()
  })

  it('string payloads keep the locked JSON-quoted representation', () => {
    emit('simulation_event', 'hello')
    expect(within(log()).getByText('"hello"')).toBeInTheDocument()
  })

  it('preview truncation boundary is exact: 100 stays whole, 101 truncates to 100 + ellipsis', () => {
    // JSON.stringify adds two quote characters: 98 a's -> exactly 100.
    emit('node_update', 'a'.repeat(98))
    // 99 a's -> 101 serialized -> sliced to 100 + '...'.
    emit('node_update', 'a'.repeat(99))
    const previews = entries().map(e => (e as HTMLElement).lastElementChild!.textContent!)
    // Newest first: the 101-char payload is previews[0].
    expect(previews[1]).toBe(`"${'a'.repeat(98)}"`)
    expect(previews[1]).toHaveLength(100)
    expect(previews[0]).toBe(`"${'a'.repeat(99)}"`.slice(0, 100) + '...')
    expect(previews[0]).toHaveLength(103)
  })

  it('orders newest first', () => {
    emit('simulation_event', { seq: 1 })
    emit('node_update', { seq: 2 })
    emit('edge_update', { seq: 3 })
    expect(entries().map(e => e.getAttribute('data-event-channel'))).toEqual([
      'edge_update',
      'node_update',
      'simulation_event',
    ])
  })

  it('caps retention at exactly 50, dropping the oldest', () => {
    for (let i = 1; i <= 55; i++) emit('node_update', { seq: i })
    const list = entries()
    expect(list).toHaveLength(50)
    expect(list[0]).toHaveTextContent('{"seq":55}')
    expect(list[49]).toHaveTextContent('{"seq":6}')
    expect(summary()).toHaveTextContent('Showing 50 of 50 events')
  })

  it('renders malicious HTML as inert text', () => {
    emit('simulation_event', '<img src=x onerror="window.__pwned=true">')
    expect(log().querySelector('img')).toBeNull()
    expect(within(log()).getByText('"<img src=x onerror=\\"window.__pwned=true\\">"')).toBeInTheDocument()
    expect((window as Window & { __pwned?: boolean }).__pwned).toBeUndefined()
  })
})

describe('EventFeed operations', () => {
  beforeEach(() => {
    render(<EventFeed simClient={asClient()} />)
  })

  it('channel filter buttons expose semantic pressed state and hide without dropping', () => {
    emit('node_update', { seq: 1 })
    emit('edge_update', { seq: 2 })
    const nodeButton = screen.getByRole('button', { name: 'node_update' })
    expect(nodeButton).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(nodeButton)
    expect(nodeButton).toHaveAttribute('aria-pressed', 'false')
    expect(entries().map(e => e.getAttribute('data-event-channel'))).toEqual(['edge_update'])
    expect(summary()).toHaveTextContent('Showing 1 of 2 events')

    fireEvent.click(nodeButton) // re-enable: nothing was lost
    expect(entries()).toHaveLength(2)
    expect(summary()).toHaveTextContent('Showing 2 of 2 events')
  })

  it('search is trimmed and case-insensitive over channel and preview; plain string only', () => {
    emit('node_update', { name: 'Alpha' })
    emit('edge_update', { name: 'beta' })
    const box = screen.getByLabelText('Search events')

    fireEvent.change(box, { target: { value: '  ALPHA  ' } })
    expect(entries().map(e => e.getAttribute('data-event-channel'))).toEqual(['node_update'])

    // Regex metacharacters match literally (or nothing) — never as patterns.
    fireEvent.change(box, { target: { value: '.*' } })
    expect(entries()).toHaveLength(0)
    expect(log()).toHaveTextContent('No events match the current filters.')

    fireEvent.change(box, { target: { value: '' } })
    expect(entries()).toHaveLength(2)
  })

  it('Clear is disabled when empty, empties the feed, and later events still arrive', () => {
    const clear = screen.getByRole('button', { name: 'Clear' })
    expect(clear).toBeDisabled()

    emit('node_update', { seq: 1 })
    expect(clear).toBeEnabled()
    fireEvent.click(clear)
    expect(entries()).toHaveLength(0)
    expect(summary()).toHaveTextContent('No events retained.')

    emit('node_update', { seq: 2 })
    expect(entries()).toHaveLength(1)
  })
})

describe('EventFeed export', () => {
  // jsdom leaves the blob-URL store unimplemented; deterministic fakes are
  // installed per test and the original property state restored afterwards.
  let createSpy: ReturnType<typeof vi.fn>
  let revokeSpy: ReturnType<typeof vi.fn>
  let originalCreate: PropertyDescriptor | undefined
  let originalRevoke: PropertyDescriptor | undefined
  let clicked: Array<{ href: string; download: string }>

  beforeEach(() => {
    vi.useFakeTimers()
    createSpy = vi.fn(() => 'blob:unit-test')
    revokeSpy = vi.fn()
    originalCreate = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    originalRevoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: createSpy })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: revokeSpy })
    clicked = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.href, download: this.download })
    })
    render(<EventFeed simClient={asClient()} />)
  })

  afterEach(() => {
    const urlRecord = URL as unknown as Record<string, unknown>
    if (originalCreate) Object.defineProperty(URL, 'createObjectURL', originalCreate)
    else delete urlRecord.createObjectURL
    if (originalRevoke) Object.defineProperty(URL, 'revokeObjectURL', originalRevoke)
    else delete urlRecord.revokeObjectURL
    vi.useRealTimers()
  })

  it('is disabled with nothing visible (empty feed or filtered-empty)', () => {
    const exportButton = screen.getByRole('button', { name: 'Export visible JSON' })
    expect(exportButton).toBeDisabled()
    emit('node_update', { seq: 1 })
    expect(exportButton).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'node_update' })) // filter it out
    expect(exportButton).toBeDisabled()
  })

  it('exports visible events newest-first with ORIGINAL payloads (never truncated previews), null-normalized', async () => {
    const long = 'x'.repeat(500)
    emit('node_update', { blob: long })   // preview truncates; export must not
    emit('edge_update')                    // omitted payload -> explicit null
    emit('simulation_event', { keep: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'simulation_event' })) // hide channel

    fireEvent.click(screen.getByRole('button', { name: 'Export visible JSON' }))

    expect(createSpy).toHaveBeenCalledTimes(1)
    expect(clicked).toEqual([{ href: 'blob:unit-test', download: 'event-feed-export.json' }])

    const blob = createSpy.mock.calls[0][0] as Blob
    expect(blob.type).toBe('application/json')
    const doc = JSON.parse(await blob.text()) as {
      schema: string
      version: number
      events: Array<{ channel: string; timestamp: number; payload: unknown }>
    }
    expect(doc.schema).toBe('utilityfog.event-feed-export')
    expect(doc.version).toBe(1)
    // Visible only (simulation_event filtered out), newest first.
    expect(doc.events.map(e => e.channel)).toEqual(['edge_update', 'node_update'])
    expect(doc.events[0].payload).toBeNull()
    expect(doc.events[1].payload).toEqual({ blob: long })

    // Deferred revocation: not synchronous, exactly once after the macrotask.
    expect(revokeSpy).not.toHaveBeenCalled()
    vi.runAllTimers()
    expect(revokeSpy).toHaveBeenCalledTimes(1)
    expect(revokeSpy).toHaveBeenCalledWith('blob:unit-test')
  })
})
