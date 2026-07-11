// Package X: the full ConnectionBadge accessibility contract (the U
// foundation slice covered only the basics).
//
// The pulsing class is queried BY CLASS NAME deliberately: the class is
// itself the contract — the prefers-reduced-motion stylesheet keys off
// `.connection-badge-dot--pulsing`, so its presence/absence is the
// observable API for motion behavior in jsdom (which computes no CSS
// animations).
import { describe, it, expect } from 'vitest'
import { StrictMode } from 'react'
import { render, screen } from '@testing-library/react'
import ConnectionBadge from '../src/components/ConnectionBadge'

const dot = (container: HTMLElement) =>
  container.querySelector('.connection-badge [aria-hidden="true"]')

describe('ConnectionBadge contract', () => {
  it('exposes exactly one atomic status region whose text is the whole announcement', () => {
    render(<ConnectionBadge isConnected={false} />)
    const regions = screen.getAllByRole('status')
    expect(regions).toHaveLength(1)
    expect(regions[0]).toHaveAttribute('aria-atomic', 'true')
    expect(regions[0]).toHaveTextContent(/^Disconnected$/)
  })

  it('rerenders update the SAME live region — no duplicates across state flips', () => {
    const { rerender } = render(<ConnectionBadge isConnected={false} />)
    const region = screen.getByRole('status')
    for (const state of [true, false, true, false, true]) {
      rerender(<ConnectionBadge isConnected={state} />)
      const regions = screen.getAllByRole('status')
      expect(regions).toHaveLength(1)
      expect(regions[0]).toBe(region) // identity preserved: announcements, not replacements
      expect(regions[0]).toHaveTextContent(state ? /^Connected$/ : /^Disconnected$/)
    }
  })

  it('StrictMode renders a single region', () => {
    render(
      <StrictMode>
        <ConnectionBadge isConnected={true} />
      </StrictMode>,
    )
    expect(screen.getAllByRole('status')).toHaveLength(1)
    expect(screen.getByRole('status')).toHaveTextContent('Connected')
  })

  it('the decorative dot stays hidden and pulses only while connected', () => {
    const { container, rerender } = render(<ConnectionBadge isConnected={false} />)
    const disconnectedDot = dot(container)
    expect(disconnectedDot).not.toBeNull()
    expect(disconnectedDot).toHaveAttribute('aria-hidden', 'true')
    expect(disconnectedDot).not.toHaveClass('connection-badge-dot--pulsing')

    rerender(<ConnectionBadge isConnected={true} />)
    expect(dot(container)).toHaveClass('connection-badge-dot--pulsing')

    rerender(<ConnectionBadge isConnected={false} />)
    expect(dot(container)).not.toHaveClass('connection-badge-dot--pulsing')
  })

  it('the status text is the badge\'s entire accessible content (dot contributes nothing)', () => {
    render(<ConnectionBadge isConnected={true} />)
    const region = screen.getByRole('status')
    expect(region.textContent).toBe('Connected')
  })
})
