// Package AJ (amendment): the ONE shared readiness gate for every spec
// that drives the application through a fake-socket registry.
//
// Why this exists (portability audit receipt): waiting for #root alone
// raced the post-commit subscription effects — Chromium happened to win
// the race, WebKit lost it (events injected before EventFeed subscribed
// were silently missed), and a bootstrap that dereferenced
// `socks[socks.length - 1]` straight after #root could observe an
// ABSENT registry entry and throw. Semantic readiness is two-phase:
//   1. the application's CURRENT socket exists in the registry (the
//      active-application-socket predicate below), and
//   2. two paint ticks have passed, so the subscription effects that
//      attach onmessage handlers have flushed in every engine.
import type { Page } from '@playwright/test'

// PAGE-CONTEXT predicate — fully self-contained (references only its
// argument and window) so Playwright can serialize it into the page for
// waitForFunction, and vitest can call it directly under jsdom. Optional
// chaining throughout: an absent or empty registry, or a hole in it, is
// simply "not ready yet" — never a crash.
//
// "Active application socket": at least `minCount` registry entries whose
// url contains `path`, and the LATEST such entry (the application's
// current socket) is not CLOSED. Sockets begin CONNECTING (0) and the
// specs open them explicitly, so the predicate deliberately requires
// "not CLOSED (3)", not "OPEN (1)".
export function applicationSocketReady(arg: { path: string; minCount: number }): boolean {
  const w = window as unknown as {
    __fakeSockets?: Array<{ url?: unknown; readyState?: unknown } | undefined>
  }
  const matching = (w.__fakeSockets ?? []).filter(s =>
    String(s?.url ?? '').includes(arg.path),
  )
  if (matching.length < arg.minCount) return false
  const current = matching[matching.length - 1]
  return current?.readyState !== 3
}

export interface WaitForApplicationSocketOptions {
  // Substring identifying application sockets in the registry.
  path?: string
  // For reconnect scenarios: wait until this many application sockets
  // have been created (the newest is the active one).
  minCount?: number
}

export async function waitForApplicationSocket(
  page: Page,
  options?: WaitForApplicationSocketOptions,
): Promise<void> {
  const arg = { path: options?.path ?? '/ws', minCount: options?.minCount ?? 1 }
  await page.waitForFunction(applicationSocketReady, arg)
  // The required paint/effect turn: two rAF ticks after the socket
  // exists guarantee the commit that created it has painted and its
  // subscription effects have run before any test injects traffic.
  await page.evaluate(
    () =>
      new Promise(resolve =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  )
}
