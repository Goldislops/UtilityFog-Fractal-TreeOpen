import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

// Narrow error boundary for the REPLACEABLE 2D/3D view surface only — the
// application shell (controls, event feed, connection badge) deliberately
// sits outside it, so an unexpected render exception in the active view
// can no longer unmount the whole tree (the failure mode the ingestion
// validators guard against upstream; this is the last line).
//
// Containment contract:
//  - When healthy, children render UNWRAPPED — zero layout impact.
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

interface ViewErrorBoundaryProps {
  // Names the guarded surface in the fallback message ("3D network view").
  viewLabel: string
  // Invoked when the user clicks Retry, BEFORE the boundary clears its
  // failed state — the owner can mint fresh lazy-loaded children so a
  // cached chunk-load rejection is retried (Package AG).
  onRetry?: () => void
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

  static getDerivedStateFromError(): ViewErrorBoundaryState {
    return { failed: true }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // The SINGLE application-owned diagnostic for this failure — error plus
    // the component stack that locates it. (React's own development-mode
    // logging is separate and not this boundary's contract.)
    console.error('View render failed:', error, info.componentStack)
  }

  handleRetry = (): void => {
    this.props.onRetry?.()
    this.setState({ failed: false })
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <div
          role="alert"
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '12px',
            color: 'white',
            backgroundColor: '#1a1a1a',
          }}
        >
          <p style={{ margin: 0 }}>The {this.props.viewLabel} failed to render.</p>
          <button
            type="button"
            style={{ minWidth: 44, minHeight: 44 }}
            onClick={this.handleRetry}
          >
            Retry {this.props.viewLabel}
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
