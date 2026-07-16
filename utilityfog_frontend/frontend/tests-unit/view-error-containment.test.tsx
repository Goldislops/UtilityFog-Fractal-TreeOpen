// Package AB: view failure containment — an unexpected active-view render
// exception must never unmount the application shell.
//
// The WebGL-heavy views are mocked at the module seam (no real WebGL in
// unit tests) with CONTROLLABLE failure flags, so genuine render throws
// exercise the real ViewErrorBoundary inside the real App.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { StrictMode } from 'react'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import App from '../src/App'

const failures = { v3d: false, v2d: false, v3dError: null as Error | null }

vi.mock('../src/viz3d/NetworkView3D', () => ({
  default: () => {
    if (failures.v3dError) throw failures.v3dError
    if (failures.v3d) throw new Error('synthetic 3D render failure')
    return <div data-testid="view-3d" />
  },
}))
vi.mock('../src/components/NetworkView2D', () => ({
  default: () => {
    if (failures.v2d) throw new Error('synthetic 2D render failure')
    return <div data-testid="view-2d" />
  },
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
  serverOpen() {
    this.readyState = 1
    this.onopen?.({})
  }
}

const live = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
const shellAlive = () => {
  expect(screen.getByRole('button', { name: '2D View' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '3D View' })).toBeInTheDocument()
  expect(screen.getAllByRole('status')).toHaveLength(1)
  expect(screen.getAllByRole('log')).toHaveLength(1)
}
const boundaryReports = () =>
  vi.mocked(console.error).mock.calls.filter(args => args[0] === 'View render failed:')
const reportCount = () => boundaryReports().length

beforeEach(() => {
  failures.v3d = false
  failures.v2d = false
  failures.v3dError = null
  vi.stubGlobal('WebSocket', FakeWebSocket)
  FakeWebSocket.instances = []
  vi.spyOn(console, 'log').mockImplementation(() => {})
  // React's own development error output also lands on console.error; the
  // bounded-report assertions filter to the boundary's exact channel.
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('view failure containment', () => {
  it('a throwing 3D view shows an accessible fallback while the shell survives', async () => {
    failures.v3d = true
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The 3D network view failed to render.')
    expect(screen.queryByTestId('view-3d')).not.toBeInTheDocument()
    shellAlive()
    expect(reportCount()).toBe(1) // reported once, not swallowed
  })

  it('a throwing 2D view is contained identically', async () => {
    failures.v2d = true
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The 2D network view failed to render.')
    shellAlive()
    expect(reportCount()).toBe(1)
  })

  it('connection state survives a view failure (badge keeps announcing)', async () => {
    failures.v3d = true
    render(<App />)
    await screen.findByRole('alert') // failure settled: the transient loading status is gone
    act(() => live().serverOpen())
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(FakeWebSocket.instances).toHaveLength(1) // no hidden reconnect
  })

  it('switching away recovers: the healthy view renders with no fallback', async () => {
    failures.v3d = true
    render(<App />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    expect(await screen.findByTestId('view-2d')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('switching back after the failure clears remounts a healthy view (boundary reset)', async () => {
    failures.v3d = true
    render(<App />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    failures.v3d = false
    fireEvent.click(screen.getByRole('button', { name: '3D View' }))
    expect(await screen.findByTestId('view-3d')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('explicit retry remounts only the failed view', async () => {
    failures.v3d = true
    render(<App />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    failures.v3d = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry 3D network view' }))
    expect(await screen.findByTestId('view-3d')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    shellAlive()
  })

  it('repeated failure stays bounded: each retry yields one fallback and one report — no loop', async () => {
    failures.v3d = true
    render(<App />)
    await screen.findByRole('alert')
    expect(reportCount()).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: 'Retry 3D network view' })) // still failing
    await screen.findByRole('alert')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(reportCount()).toBe(2) // one more failure, one more report — user-paced, no retry loop
    fireEvent.click(screen.getByRole('button', { name: 'Retry 3D network view' }))
    await screen.findByRole('alert')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(reportCount()).toBe(3)
  })

  it('explicit retry recovers the 2D view identically (fresh lazy instance)', async () => {
    failures.v2d = true
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    await screen.findByRole('alert')
    failures.v2d = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry 2D network view' }))
    expect(await screen.findByTestId('view-2d')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('successful views never show the fallback', async () => {
    render(<App />)
    expect(await screen.findByTestId('view-3d')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    expect(await screen.findByTestId('view-2d')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('StrictMode: single fallback, singular connection lifecycle, no duplicate live regions', async () => {
    failures.v3d = true
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
    await screen.findByRole('alert')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(FakeWebSocket.instances).toHaveLength(2) // documented dev-mode double-mount artifact
    act(() => live().serverOpen())
    expect(screen.getAllByRole('status')).toHaveLength(1)
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
    expect(screen.getAllByRole('log')).toHaveLength(1)
  })
})

describe('AB audit amendments', () => {
  it('the single diagnostic carries the error AND the locating componentStack', async () => {
    failures.v3d = true
    render(<App />)
    await screen.findByRole('alert')
    const reports = boundaryReports()
    expect(reports).toHaveLength(1)
    const [, error, componentStack] = reports[0]
    expect(error).toBeInstanceOf(Error)
    expect((error as Error).message).toBe('synthetic 3D render failure')
    expect(typeof componentStack).toBe('string')
    expect((componentStack as string).length).toBeGreaterThan(0)
    // React dev logging also hits console.error — the boundary-owned
    // channel stays exactly one call, distinguished by its first argument.
    expect(vi.mocked(console.error).mock.calls.length).toBeGreaterThanOrEqual(reports.length)
  })

  it('the Retry control is an explicit type="button" (never an implicit submit)', async () => {
    failures.v3d = true
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Retry 3D network view' }))
      .toHaveAttribute('type', 'button')
  })
})

describe('retry focus recovery (Package AK, success-aware amendment)', () => {
  it('successful Retry moves focus to the recovered view region (never dropped on body)', async () => {
    failures.v3d = true
    render(<App />)
    const retry = await screen.findByRole('button', { name: 'Retry 3D network view' })
    retry.focus()
    expect(retry).toHaveFocus()

    failures.v3d = false
    fireEvent.click(retry)
    await screen.findByTestId('view-3d')
    // Success-aware focus: onRecovered fires from the post-reveal commit
    // probe, so the region receives focus only after the view committed.
    await waitFor(() => {
      expect(screen.getByRole('region', { name: '3D network view' })).toHaveFocus()
    })
  })

  it('a retry that FAILS AGAIN keeps focus on the new Retry button, not the region', async () => {
    failures.v3d = true
    render(<App />)
    const retry = await screen.findByRole('button', { name: 'Retry 3D network view' })
    retry.focus()
    fireEvent.click(retry) // still failing: the old button unmounts, a new one renders
    const retryAgain = await screen.findByRole('button', { name: 'Retry 3D network view' })
    // The keyboard user must stay in the retry loop: focus is restored to
    // the NEW Retry button, and the region is never focused (the view
    // never committed).
    await waitFor(() => expect(retryAgain).toHaveFocus())
    expect(screen.queryByRole('region', { name: '3D network view' })).not.toHaveFocus()
  })

  it('eventual success after repeated failures: the region is focused exactly then', async () => {
    failures.v3d = true
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry 3D network view' }))
    await screen.findByRole('alert') // first retry failed again
    failures.v3d = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry 3D network view' }))
    await screen.findByTestId('view-3d')
    await waitFor(() => {
      expect(screen.getByRole('region', { name: '3D network view' })).toHaveFocus()
    })
  })

  it('ordinary lazy loading steals no focus', async () => {
    render(<App />)
    const button2d = screen.getByRole('button', { name: '2D View' })
    button2d.focus()
    fireEvent.click(button2d)
    await screen.findByTestId('view-2d')
    expect(button2d).toHaveFocus() // load completed without focus theft
  })

  it('a FIRST failure (no retry involved) steals no focus either', async () => {
    render(<App />)
    await screen.findByTestId('view-3d')
    const button2d = screen.getByRole('button', { name: '2D View' })
    button2d.focus()
    failures.v2d = true
    fireEvent.click(button2d)
    await screen.findByRole('alert')
    // The boundary self-focuses its button ONLY inside a retry cycle.
    expect(button2d).toHaveFocus()
  })
})


describe('chunk-load failure recovery at the App seam (Package AL amendment)', () => {
  const chunkError = () =>
    new TypeError('Failed to fetch dynamically imported module: http://localhost:4173/x.tsx')

  // vitest sniffs the engine import-failure messages as its OWN module
  // failures when React dev re-reports them on the window channel — mark
  // them handled for this describe (see chunk-load-recovery.test.tsx).
  const swallowWindowError = (e: ErrorEvent) => e.preventDefault()
  beforeEach(() => window.addEventListener('error', swallowWindowError))
  afterEach(() => window.removeEventListener('error', swallowWindowError))

  it('a chunk-shaped failure presents Reload application, advertises NO Retry, and the shell survives', async () => {
    failures.v3dError = chunkError()
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('failed to download')
    expect(screen.getByRole('button', { name: 'Reload application' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument()
    shellAlive()
  })

  it('switch-away/back: the healthy view works, the fresh boundary re-classifies, one socket throughout', async () => {
    failures.v3dError = chunkError()
    render(<App />)
    await screen.findByRole('button', { name: 'Reload application' })
    fireEvent.click(screen.getByRole('button', { name: '2D View' }))
    expect(await screen.findByTestId('view-2d')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '3D View' }))
    expect(await screen.findByRole('button', { name: 'Reload application' })).toBeInTheDocument()
    shellAlive()
    expect(FakeWebSocket.instances).toHaveLength(1) // no hidden reconnect
  })
})

describe('focus-indicator decision and fallback styling contracts (source-level)', () => {
  // The stylesheet is the single owner of these decisions; :focus-visible
  // matching on programmatic focus is deliberately left to each UA (see
  // the DECISION comment in index.css), so the testable contract is that
  // we neither removed the indicator nor styled by role. Read from the
  // vitest root (`?raw` is intercepted empty by vitest's CSS pipeline;
  // vitest always runs at the frontend root via the npm scripts) and
  // strip comments — the assertions target RULES, and the documentation
  // comments deliberately name the rejected patterns.
  const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8').replace(
    /\/\*[\s\S]*?\*\//g,
    '',
  )

  it('the tabIndex=-1 view region keeps the :focus-visible indicator (documented decision, not suppressed)', () => {
    expect(css).toContain('[tabindex]:focus-visible')
    expect(css).not.toMatch(/outline:\s*none/)
  })

  it('fallback styling binds to the explicit class, never the alert ROLE', () => {
    expect(css).toContain('.view-error-fallback')
    expect(css).toContain('.view-retry-button')
    expect(css).not.toMatch(/\[role=["']?alert["']?\]/)
  })

  it('the static Retry dimensions live in CSS, and the button carries the class', async () => {
    expect(css).toMatch(/\.view-retry-button[^{]*\{[^}]*min-width:\s*44px/)
    expect(css).toMatch(/\.view-retry-button[^{]*\{[^}]*min-height:\s*44px/)
    failures.v3d = true
    render(<App />)
    const retry = await screen.findByRole('button', { name: 'Retry 3D network view' })
    expect(retry).toHaveClass('view-retry-button')
    expect(retry.getAttribute('style')).toBeNull() // no inline dimensions remain
  })
})
