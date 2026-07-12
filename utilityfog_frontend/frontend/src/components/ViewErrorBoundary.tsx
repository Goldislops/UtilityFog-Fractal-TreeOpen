import { Component, Suspense, createRef, useEffect } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

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
//  - On failure: an accessible role="alert" fallback with a concise
//    message and a Retry button that remounts ONLY the failed view.
//  - Retry is user-initiated only — no automatic retry loop, no hidden
//    reconnect (the SimBridge client lives above this boundary and is
//    untouched by view failures).
//  - Switching views unmounts this boundary instance, so the replacement
//    view always starts with a fresh, un-failed boundary.
//  - Errors are not swallowed: each failure is reported exactly once
//    through the established bounded diagnostic channel (console.error),
//    alongside React's own development error output.
//
// Focus contract (Package AK amendment, success-aware):
//  - Clicking Retry moves focus NOWHERE by itself. The old Retry button
//    unmounts, and where focus lands next depends on the OUTCOME:
//  - SUCCESS — the retried children COMMIT (in suspenseFallback mode:
//    the suspense reveal, observed by the commit probe): `onRecovered`
//    fires exactly once, and the owner moves focus (App focuses the
//    labelled view region).
//  - REPEATED FAILURE — the boundary catches again: focus is restored to
//    the NEW Retry button, keeping a keyboard user inside the retry loop
//    instead of dropping them on <body>.
//  - A FIRST failure (no retry in flight) moves focus nowhere — the
//    boundary self-focuses only inside a user-initiated retry cycle, so
//    ordinary loads and first failures steal nothing.

// Commit probe: rendered INSIDE the suspense boundary, after the real
// children. Its effect can only run once the suspended children have
// revealed — i.e. the child commit the focus contract keys on. It fires
// on every subsequent commit too; the boundary gates on its retry flag.
function RecoveryProbe({ onCommit }: { onCommit: () => void }) {
  useEffect(() => {
    onCommit()
  })
  return null
}

interface ViewErrorBoundaryProps {
  // Names the guarded surface in the fallback message ("3D network view").
  viewLabel: string
  // Invoked when the user clicks Retry, BEFORE the boundary clears its
  // failed state — the owner can mint fresh lazy-loaded children so a
  // cached chunk-load rejection is retried (Package AG).
  onRetry?: () => void
  // Success-aware recovery callback (Package AK): invoked exactly once
  // when a user-initiated Retry is followed by a successful child commit.
  // Never invoked for ordinary first loads.
  onRecovered?: () => void
  // When provided, the boundary owns the pending surface: children render
  // inside <Suspense fallback={suspenseFallback}> with the commit probe.
  // When absent, children render unwrapped (owners with their own
  // Suspense keep exactly the old behavior; onRecovered stays silent).
  suspenseFallback?: ReactNode
  children: ReactNode
}

interface ViewErrorBoundaryState {
  failed: boolean
}

export default class ViewErrorBoundary extends Component<
  ViewErrorBoundaryProps,
  ViewErrorBoundaryState
> {
  state: ViewErrorBoundaryState = { failed: false }

  // True from a Retry click until its outcome (success commit or repeated
  // failure) is known. An instance field, not state: it must never cause
  // a render of its own.
  private retryPending = false

  private retryButtonRef = createRef<HTMLButtonElement>()

  static getDerivedStateFromError(): Partial<ViewErrorBoundaryState> {
    return { failed: true }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // The SINGLE application-owned diagnostic for this failure — error plus
    // the component stack that locates it. (React's own development-mode
    // logging is separate and not this boundary's contract.)
    console.error('View render failed:', error, info.componentStack)
  }

  componentDidUpdate(_prevProps: ViewErrorBoundaryProps, prevState: ViewErrorBoundaryState): void {
    // A failure that lands while a retry is in flight is a REPEATED
    // failure: the fresh fallback has committed, so its new Retry button
    // exists — restore keyboard focus there and close the cycle.
    if (this.state.failed && !prevState.failed && this.retryPending) {
      this.retryPending = false
      this.retryButtonRef.current?.focus()
    }
  }

  handleRetry = (): void => {
    this.retryPending = true
    this.props.onRetry?.()
    this.setState({ failed: false })
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
      return (
        <div role="alert" className="view-error-fallback">
          <p>The {this.props.viewLabel} failed to render.</p>
          <button
            type="button"
            className="view-retry-button"
            ref={this.retryButtonRef}
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
