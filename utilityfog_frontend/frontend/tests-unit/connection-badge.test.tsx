// Foundation suite, part 2: one simple component rendered through Testing
// Library with accessible-output assertions, plus a direct demonstration
// that DOM state cannot leak between tests (the setup.ts cleanup contract).
//
// Scope note: this is the FOUNDATION slice only — the full ConnectionBadge
// accessibility contract (live-region atomicity across rerenders, duplicate
// regions, reduced-motion) belongs to Package X.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ConnectionBadge from '../src/components/ConnectionBadge'

describe('ConnectionBadge (foundation)', () => {
  it('disconnected: exposes exactly one status live region reading "Disconnected"', () => {
    render(<ConnectionBadge isConnected={false} />)
    const regions = screen.getAllByRole('status')
    expect(regions).toHaveLength(1)
    expect(regions[0]).toHaveTextContent('Disconnected')
    expect(regions[0]).toHaveAttribute('aria-atomic', 'true')
  })

  it('connected: the same region reads "Connected" and the dot stays decorative', () => {
    const { container } = render(<ConnectionBadge isConnected={true} />)
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
    // The indicator dot is presentation only — queried by its structural
    // class (independent of the attribute under test), then the hidden
    // contract asserted explicitly.
    const dot = container.querySelector('.connection-badge-dot')
    expect(dot).not.toBeNull()
    expect(dot).toHaveAttribute('aria-hidden', 'true')
    expect(dot).toHaveTextContent('')
  })

  it('cleanup contract: previous renders are gone before this test runs', () => {
    // The two tests above rendered badges; explicit cleanup in setup.ts
    // must have removed them. queryAllByRole returns [] rather than
    // throwing, so this asserts the absence directly.
    expect(screen.queryAllByRole('status')).toHaveLength(0)
    expect(document.body).toBeEmptyDOMElement()

    // And rendering fresh works from the clean slate.
    render(<ConnectionBadge isConnected={false} />)
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })
})
