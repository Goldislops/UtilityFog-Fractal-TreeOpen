// Package AG: lazy view delivery — the shell renders independently of view
// code; chunk-load rejection reaches the existing ViewErrorBoundary; Retry
// re-runs the import.
//
// The heavy views are mocked at the module seam (jsdom renders no WebGL);
// the DYNAMIC import path in App resolves through the same mocks. A
// direct-harness section proves the lazy-rejection contract with a
// controllable factory (vi.mock factories cannot toggle rejection per
// test).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { lazy, Suspense, useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import App from '../src/App'
import ViewErrorBoundary from '../src/components/ViewErrorBoundary'
import appSource from '../src/App.tsx?raw'

vi.mock('../src/viz3d/NetworkView3D', () => ({
  default: () => <div data-testid="view-3d" />,
}))
vi.mock('../src/components/NetworkView2D', () => ({
  default: () => <div data-testid="view-2d" />,
}))

// Package AL: jsdom has no WebGL, so the capability gate would fail
// closed and block the mocked 3D view. These suites test view
// lifecycle, not capability - the probe is pinned supported here.
vi.mock('../src/viz3d/webglSupport', () => ({ probeWebGLSupport: () => true }))

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
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', FakeWebSocket)
  FakeWebSocket.instances = []
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('lazy view delivery through App', () => {
  it('no eager static import of a heavy view module remains in App (source contract)', () => {
    expect(appSource).not.toMatch(/^import .*NetworkView3D/m)
    expect(appSource).not.toMatch(/^import .*NetworkView2D/m)
    expect(appSource).toContain("import('./viz3d/NetworkView3D')")
    expect(appSource).toContain("import('./components/NetworkView2D')")
  })

  it('the shell renders immediately with an accessible loading status inside the region, then the view arrives', async () => {
    render(<App />)
    // Shell is up synchronously — controls, badge, feed — while the view
    // chunk is still pending.
    expect(screen.getByRole('button', { name: '3D View' })).toBeInTheDocument()
    expect(screen.getAllByRole('log')).toHaveLength(1)
    const region = screen.getByRole('region', { name: '3D network view' })
    const loading = screen.getByText('Loading 3D network view…')
    expect(region.contains(loading)).toBe(true)
    expect(loading).toHaveAttribute('role', 'status')

    expect(await screen.findByTestId('view-3d')).toBeInTheDocument()
    // Steady state: the transient loading status is gone; the badge is the
    // single status region again.
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })

  it('exactly one SimBridge connection lineage regardless of lazy loading', async () => {
    render(<App />)
    await screen.findByTestId('view-3d')
    expect(FakeWebSocket.instances).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    await screen.findByTestId('view-2d')
    expect(FakeWebSocket.instances).toHaveLength(1) // switching never reconnects
  })

  it('switching views remains fresh and deterministic with exactly one active view', async () => {
    render(<App />)
    await screen.findByTestId('view-3d')
    for (const [button, testId] of [
      ['2D View', 'view-2d'],
      ['3D View', 'view-3d'],
      ['2D View', 'view-2d'],
    ] as const) {
      fireEvent.click(screen.getByRole('button', { name: button }))
      expect(await screen.findByTestId(testId)).toBeInTheDocument()
      expect(screen.getAllByRole('region')).toHaveLength(1)
    }
  })
})

describe('lazy rejection reaches the boundary (direct harness)', () => {
  // A controllable factory: first import rejects, the retry resolves —
  // exactly the failed-chunk-then-network-recovers sequence.
  function Harness() {
    const attemptRef = { current: 0 }
    const factory = () => {
      attemptRef.current++
      return attemptRef.current === 1
        ? Promise.reject(new Error('chunk load failed'))
        : Promise.resolve({ default: () => <div data-testid="late-view" /> })
    }
    const [LazyView, setLazyView] = useState(() => lazy(factory))
    return (
      <ViewErrorBoundary
        viewLabel="test view"
        onRetry={() => setLazyView(() => lazy(factory))}
      >
        <Suspense fallback={<div role="status">Loading test view…</div>}>
          <LazyView />
        </Suspense>
      </ViewErrorBoundary>
    )
  }

  it('a rejected chunk shows the boundary fallback; Retry re-imports and mounts the view', async () => {
    render(<Harness />)
    // Rejection propagates through Suspense into the boundary.
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The test view failed to render.')
    const reports = vi
      .mocked(console.error)
      .mock.calls.filter(args => args[0] === 'View render failed:')
    expect(reports).toHaveLength(1)
    expect((reports[0][1] as Error).message).toBe('chunk load failed')

    // Retry mints a fresh lazy instance → the import re-runs → the view
    // mounts. No reconnect side effects exist in this harness by
    // construction (the boundary owns no network).
    fireEvent.click(screen.getByRole('button', { name: 'Retry test view' }))
    expect(await screen.findByTestId('late-view')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('switch-away/back retries a failed chunk import (audit amendment)', () => {
  // Two-view direct harness replicating App's selection semantics with
  // CONTROLLABLE import factories (vi.mock factories cannot reject
  // cleanly): switching TO a view mints a fresh lazy for the target;
  // clicking the active view is a no-op.
  function TwoViewHarness({ factories }: { factories: { a: () => Promise<{ default: () => JSX.Element }>; b: () => Promise<{ default: () => JSX.Element }> } }) {
    const [view, setView] = useState<'a' | 'b'>('a')
    const [LazyA, setLazyA] = useState(() => lazy(factories.a))
    const [LazyB, setLazyB] = useState(() => lazy(factories.b))
    const selectView = (target: 'a' | 'b') => {
      if (target === view) return
      if (target === 'a') setLazyA(() => lazy(factories.a))
      else setLazyB(() => lazy(factories.b))
      setView(target)
    }
    const Active = view === 'a' ? LazyA : LazyB
    return (
      <div>
        <button type="button" onClick={() => selectView('a')}>go a</button>
        <button type="button" onClick={() => selectView('b')}>go b</button>
        {/* key mirrors App's load-bearing per-view boundary remount */}
        <ViewErrorBoundary key={view} viewLabel={`${view} view`}>
          <Suspense fallback={<div role="status">loading…</div>}>
            <Active />
          </Suspense>
        </ViewErrorBoundary>
      </div>
    )
  }

  it('reject A -> switch B -> return A -> the import RETRIES and recovers', async () => {
    let aAttempts = 0
    const factories = {
      a: () => {
        aAttempts++
        return aAttempts === 1
          ? Promise.reject(new Error('chunk A failed'))
          : Promise.resolve({ default: () => <div data-testid="view-a" /> })
      },
      b: () => Promise.resolve({ default: () => <div data-testid="view-b" /> }),
    }
    render(<TwoViewHarness factories={factories} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('failed to render')
    expect(aAttempts).toBe(1)

    fireEvent.click(screen.getByRole('button', { name: 'go b' }))
    expect(await screen.findByTestId('view-b')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'go a' }))
    expect(await screen.findByTestId('view-a')).toBeInTheDocument() // recovered
    expect(aAttempts).toBe(2) // switch-back minted a fresh lazy: import re-ran
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('the same recovery works for the second view', async () => {
    let bAttempts = 0
    const factories = {
      a: () => Promise.resolve({ default: () => <div data-testid="view-a" /> }),
      b: () => {
        bAttempts++
        return bAttempts === 1
          ? Promise.reject(new Error('chunk B failed'))
          : Promise.resolve({ default: () => <div data-testid="view-b" /> })
      },
    }
    render(<TwoViewHarness factories={factories} />)
    await screen.findByTestId('view-a')
    fireEvent.click(screen.getByRole('button', { name: 'go b' }))
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'go a' }))
    await screen.findByTestId('view-a')
    fireEvent.click(screen.getByRole('button', { name: 'go b' }))
    expect(await screen.findByTestId('view-b')).toBeInTheDocument()
    expect(bAttempts).toBe(2)
  })

  it('App mints a FRESH lazy on switch-back (fallback reappears) and keeps one connection', async () => {
    render(<App />)
    await screen.findByTestId('view-3d')
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    await screen.findByTestId('view-2d')

    fireEvent.click(screen.getByRole('button', { name: '3D View' }))
    // A fresh lazy instance suspends for at least one microtask even on a
    // module-cache hit — the reappearing fallback is the observable proof
    // of re-import. (The pre-amendment cached instance rendered
    // synchronously with no fallback.)
    expect(screen.getByText('Loading 3D network view…')).toBeInTheDocument()
    expect(await screen.findByTestId('view-3d')).toBeInTheDocument()
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })

  it('clicking the already-active view button neither remounts nor reloads it', async () => {
    render(<App />)
    const before = await screen.findByTestId('view-3d')
    fireEvent.click(screen.getByRole('button', { name: '3D View' }))
    expect(screen.getByTestId('view-3d')).toBe(before) // same DOM node: no remount
    expect(screen.queryByText('Loading 3D network view…')).not.toBeInTheDocument()
  })

  it('manual Retry is preserved (direct harness reject-once)', async () => {
    let attempts = 0
    const factory = () => {
      attempts++
      return attempts === 1
        ? Promise.reject(new Error('chunk failed'))
        : Promise.resolve({ default: () => <div data-testid="late-view-2" /> })
    }
    function RetryHarness() {
      const [LazyView, setLazyView] = useState(() => lazy(factory))
      return (
        <ViewErrorBoundary viewLabel="retry view" onRetry={() => setLazyView(() => lazy(factory))}>
          <Suspense fallback={<div role="status">loading…</div>}>
            <LazyView />
          </Suspense>
        </ViewErrorBoundary>
      )
    }
    render(<RetryHarness />)
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'Retry retry view' }))
    expect(await screen.findByTestId('late-view-2')).toBeInTheDocument()
  })
})
