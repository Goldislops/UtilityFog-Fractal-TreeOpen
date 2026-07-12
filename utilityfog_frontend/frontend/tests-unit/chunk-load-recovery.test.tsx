// Package AL (amendment): chunk-load failure classification and the
// Reload recovery path. The classifier is tested at its seam against the
// MEASURED engine message forms; the boundary is driven directly with a
// controllable failing child, an injected reload callback and real focus.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { isChunkLoadError } from '../src/components/chunkLoadError'
import ViewErrorBoundary from '../src/components/ViewErrorBoundary'

describe('isChunkLoadError classifier', () => {
  it.each([
    [
      'Chromium',
      new TypeError(
        'Failed to fetch dynamically imported module: http://localhost:4173/src/components/NetworkView2D.tsx',
      ),
    ],
    ['Firefox', new TypeError('error loading dynamically imported module: http://x/NetworkView2D.js')],
    ['WebKit', new TypeError('Importing a module script failed.')],
  ])('classifies the %s dynamic-import failure form', (_engine, error) => {
    expect(isChunkLoadError(error)).toBe(true)
  })

  it.each([
    ['a bare fetch() network error', new TypeError('Failed to fetch')],
    ['an ordinary render error', new Error('Cannot read properties of undefined')],
    ['a synthetic view failure', new Error('synthetic 3D render failure')],
    ['a harness rejection', new Error('chunk load failed')],
    ['an import-adjacent but different message', new Error('module evaluation failed')],
  ])('does NOT misclassify %s (false-positive guard)', (_label, error) => {
    expect(isChunkLoadError(error)).toBe(false)
  })

  it.each([
    ['a string', 'Failed to fetch dynamically imported module: x'],
    ['null', null],
    ['undefined', undefined],
    ['an object with a message field', { message: 'Importing a module script failed.' }],
  ])('rejects non-Error values: %s', (_label, value) => {
    expect(isChunkLoadError(value)).toBe(false)
  })
})

// Direct boundary harness: a child whose failure MODE is controllable.
// The REAL Chromium message form is thrown here. React dev re-reports
// boundary-caught errors on the window error channel, and vitest sniffs
// exactly these engine messages as its OWN module-import failures
// (aborting collection) — so the hooks below mark the window event
// handled (preventDefault), the standard error-boundary test recipe.
const CHUNK_ERROR = new TypeError(
  'Failed to fetch dynamically imported module: http://localhost:4173/src/x.tsx',
)
const mode: { current: 'ok' | 'render-fail' | 'chunk-fail' } = { current: 'ok' }
function Failing() {
  if (mode.current === 'render-fail') throw new Error('ordinary render failure')
  if (mode.current === 'chunk-fail') throw CHUNK_ERROR
  return <div data-testid="healthy-child" />
}

function Harness({ onReload, onRetry }: { onReload?: () => void; onRetry?: () => void }) {
  const [nonce, setNonce] = useState(0)
  return (
    <ViewErrorBoundary
      viewLabel="test view"
      onRetry={() => {
        onRetry?.()
        setNonce(n => n + 1)
      }}
      onReloadRequest={onReload}
      suspenseFallback={<div role="status">Loading…</div>}
    >
      <Failing key={nonce} />
    </ViewErrorBoundary>
  )
}

const swallowWindowError = (e: ErrorEvent) => e.preventDefault()

beforeEach(() => {
  mode.current = 'ok'
  window.addEventListener('error', swallowWindowError)
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  window.removeEventListener('error', swallowWindowError)
  vi.restoreAllMocks()
})

describe('ViewErrorBoundary chunk-load recovery', () => {
  it('a chunk-load failure presents Reload application — and does NOT advertise Retry', async () => {
    mode.current = 'chunk-fail'
    render(<Harness onReload={() => {}} />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('failed to download')
    expect(alert).toHaveTextContent('Retrying the same download cannot recover it')
    const reload = screen.getByRole('button', { name: 'Reload application' })
    expect(reload).toHaveClass('view-reload-button') // 44x44 floor lives in CSS
    expect(screen.queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument()
  })

  it('Reload invokes the INJECTED callback exactly once — no hardwired global', async () => {
    const onReload = vi.fn()
    mode.current = 'chunk-fail'
    render(<Harness onReload={onReload} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Reload application' }))
    expect(onReload).toHaveBeenCalledTimes(1)
  })

  it('an ordinary render failure keeps the user-paced Retry path (kind is per-error)', async () => {
    mode.current = 'render-fail'
    render(<Harness onReload={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Retry test view' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reload application' })).not.toBeInTheDocument()
    mode.current = 'ok'
    fireEvent.click(screen.getByRole('button', { name: 'Retry test view' }))
    expect(await screen.findByTestId('healthy-child')).toBeInTheDocument()
  })

  it('a Retry whose outcome is a CHUNK failure focuses the Reload action (cycle closes there)', async () => {
    mode.current = 'render-fail'
    render(<Harness onReload={() => {}} />)
    const retry = await screen.findByRole('button', { name: 'Retry test view' })
    retry.focus()
    mode.current = 'chunk-fail' // the fresh import attempt hits the cached-URL failure
    fireEvent.click(retry)
    const reload = await screen.findByRole('button', { name: 'Reload application' })
    expect(reload).toHaveFocus()
  })

  it('a FIRST chunk failure steals no focus (self-focus only inside a retry cycle)', async () => {
    mode.current = 'chunk-fail'
    const outside = document.createElement('button')
    document.body.appendChild(outside)
    outside.focus()
    render(<Harness onReload={() => {}} />)
    await screen.findByRole('button', { name: 'Reload application' })
    expect(outside).toHaveFocus()
    outside.remove()
  })

  it('without an injected reload callback the boundary falls back to Retry (legacy owners)', async () => {
    mode.current = 'chunk-fail'
    render(<Harness />)
    expect(await screen.findByRole('button', { name: 'Retry test view' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reload application' })).not.toBeInTheDocument()
  })
})
