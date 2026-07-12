import { Component, Suspense, createRef } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import RecoveryProbe from './RecoveryProbe'
import { isChunkLoadError } from './chunkLoadError'

// Narrow error boundary for the REPLACEABLE 2D/3D view surface only — the
// application shell (controls, event feed, connection badge) deliberately
// sits outside it, so an unexpected render exception in the active view
// can no longer unmount the whole tree (the failure mode the ingestion
// validators guard against upstream; this is the last line).
//
// Containment contract:
//  - When healthy, children render UNWRAPPED — zero layout impact —
//    unless `suspenseFallback` is provided, in which case the boundary
//    also owns the pending surface (children render inside Suspense with
//    a commit probe reporting the reveal).
//  - On failure the boundary CLASSIFIES the error (Package AL amendment):
//    - RENDER failures get an accessible role="alert" fallback with a
//      concise message and a user-paced Retry button that remounts ONLY
//      the failed view.
//    - CHUNK-LOAD failures (dynamic-import/network forms — see
//      ./chunkLoadError) get a "Reload application" action instead:
//      Chromium's module map caches a failed import URL, so a fresh
//      lazy wrapper cannot recover it and a Retry button would be a
//      false promise. The reload goes through the INJECTED
//      onReloadRequest callback (no hardwired global), no recovery is
//      guaranteed or claimed, and the same cached module URL is never
//      re-imported. If no onReloadRequest is provided, the boundary
//      falls back to the Retry presentation (legacy owners keep their
//      old behavior).
//  - Both actions are user-initiated only — no automatic retry loop, no
//    hidden reconnect (the SimBridge client lives above this boundary
//    and is untouched by view failures).
//  - Switching views unmounts this boundary instance, so the replacement
//    view always starts with a fresh, un-failed boundary.
//  - Errors are not swallowed: each failure is reported exactly once
//    through the established bounded diagnostic channel (console.error),
//    alongside React's own development error output.
//
// Focus contract (success-aware, extended for chunk failures):
//  - Clicking Retry moves focus NOWHERE by itself. Outcomes:
//  - SUCCESS — the retried children COMMIT (suspense reveal observed by
//    the commit probe): `onRecovered` fires exactly once and the owner
//    moves focus (App focuses the labelled view region).
//  - REPEATED FAILURE — the boundary catches again and focus is restored
//    to the fresh fallback's action button: the new Retry for a render
//    failure, or the Reload action when the retry outcome was a
//    chunk-load failure. The keyboard user is never dropped on <body>.
//  - A FIRST failure (no retry in flight) moves focus nowhere — the
//    boundary self-focuses only inside a user-initiated retry cycle, so
//    ordinary loads and first failures steal nothing.

interface ViewErrorBoundaryProps {
  // Names the guarded surface in the fallback message ("3D network view").
  viewLabel: string
  // Invoked when the user clicks Retry, BEFORE the boundary clears its
  // failed state — the owner can mint fresh lazy-loaded children so a
  // cached render-failure rejection is retried (Package AG).
  onRetry?: () => void
  // Success-aware recovery callback (Package AK): invoked exactly once
  // when a user-initiated Retry is followed by a successful child commit.
  // Never invoked for ordinary first loads.
  onRecovered?: () => void
  // Injected reload seam (Package AL): invoked when the user activates
  // "Reload application" on a chunk-load failure. The owner decides what
  // reloading means (App passes window.location.reload) — the boundary
  // never touches a global, which keeps this path unit-testable.
  onReloadRequest?: () => void
  // When provided, the boundary owns the pending surface: children render
  // inside <Suspense fallback={suspenseFallback}> with the commit probe.
  suspenseFallback?: ReactNode
  children: ReactNode
}

type FailureKind = 'render' | 'chunk-load'

interface ViewErrorBoundaryState {
  failed: boolean
  failureKind: FailureKind | null
}

export default class ViewErrorBoundary extends Component<
  ViewErrorBoundaryProps,
  ViewErrorBoundaryState
> {
  state: ViewErrorBoundaryState = { failed: false, failureKind: null }

  // True from a Retry click until its outcome (success commit or repeated
  // failure) is known. An instance field, not state: it must never cause
  // a render of its own.
  private retryPending = false

  // The fresh fallback's action button — Retry or Reload, whichever the
  // classification rendered — for the repeated-failure focus restore.
  private actionButtonRef = createRef<HTMLButtonElement>()

  static getDerivedStateFromError(error: unknown): Partial<ViewErrorBoundaryState> {
    return { failed: true, failureKind: isChunkLoadError(error) ? 'chunk-load' : 'render' }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // The SINGLE application-owned diagnostic for this failure — error plus
    // the component stack that locates it. (React's own development-mode
    // logging is separate and not this boundary's contract.)
    console.error('View render failed:', error, info.componentStack)
  }

  componentDidUpdate(): void {
    // A failure that lands while a retry is in flight is a REPEATED
    // failure: the fresh fallback has committed, so its action button
    // (Retry or Reload per classification) exists — restore keyboard
    // focus there and close the cycle. Guarded by the retry flag, NOT a
    // failed:false→true state transition: a synchronously-throwing child
    // fails during the retry's own render pass, so the intermediate
    // healthy tree never commits and no transition is observable. The
    // flag cannot false-positive — failed can only be true again once an
    // outcome (a catch) exists, and success clears the flag in the
    // commit probe instead.
    if (this.state.failed && this.retryPending) {
      this.retryPending = false
      this.actionButtonRef.current?.focus()
    }
  }

  handleRetry = (): void => {
    this.retryPending = true
    this.props.onRetry?.()
    this.setState({ failed: false, failureKind: null })
  }

  handleChildCommit = (): void => {
    // The probe reports every commit of the revealed children; only the
    // first one after a retry is the recovery event.
    if (this.retryPending) {
      this.retryPending = false
      this.props.onRecovered?.()
    }
  }

  render(): ReactNode {
    if (this.state.failed) {
      const chunkPath =
        this.state.failureKind === 'chunk-load' && this.props.onReloadRequest !== undefined
      if (chunkPath) {
        return (
          <div role="alert" className="view-error-fallback">
            <p>
              Part of the application failed to download, so the{' '}
              {this.props.viewLabel} cannot be shown. Retrying the same
              download cannot recover it in this browser session — reloading
              the application may help.
            </p>
            <button
              type="button"
              className="view-reload-button"
              ref={this.actionButtonRef}
              onClick={this.props.onReloadRequest}
            >
              Reload application
            </button>
          </div>
        )
      }
      return (
        <div role="alert" className="view-error-fallback">
          <p>The {this.props.viewLabel} failed to render.</p>
          <button
            type="button"
            className="view-retry-button"
            ref={this.actionButtonRef}
            onClick={this.handleRetry}
          >
            Retry {this.props.viewLabel}
          </button>
        </div>
      )
    }
    if (this.props.suspenseFallback !== undefined) {
      return (
        <Suspense fallback={this.props.suspenseFallback}>
          {this.props.children}
          <RecoveryProbe onCommit={this.handleChildCommit} />
        </Suspense>
      )
    }
    return this.props.children
  }
}
