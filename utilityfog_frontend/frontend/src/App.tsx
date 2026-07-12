/// <reference types="vite/client" />
import { useState, useEffect, useRef, lazy, Suspense } from 'react'
import ConnectionBadge from './components/ConnectionBadge'
import EventFeed from './components/EventFeed'
import ViewErrorBoundary from './components/ViewErrorBoundary'
import { SimBridgeClient } from './ws/SimBridgeClient'

// LAZY VIEW DELIVERY (Package AG): the heavy 3D/2D view modules are
// code-split behind dynamic imports — the shell (controls, badge, feed)
// renders independently of view code. No eager static import of a view
// module may appear in this file.
//
// React caches a REJECTED lazy factory permanently, so the lazy components
// live in state: the error boundary's Retry mints a fresh lazy instance
// whose mount re-runs the dynamic import — reloading a failed chunk
// without touching the SimBridge connection (which lives in this
// component, above the boundary).
const load3D = () => import('./viz3d/NetworkView3D')
const load2D = () => import('./components/NetworkView2D')

// Robust WS URL computation
const envUrl = import.meta.env.VITE_WS_URL as string | undefined;

function computeDefaultWsUrl(): string {
  const origin = window.location.origin; // http(s)://host[:port]
  const wsOrigin = origin.startsWith('https')
    ? origin.replace(/^https/, 'wss')
    : origin.replace(/^http/, 'ws');
  return `${wsOrigin}/ws?run_id=dev`;
}

const WS_URL = (envUrl && !envUrl.startsWith('ws://https://') && !envUrl.startsWith('wss://http://'))
  ? envUrl
  : computeDefaultWsUrl();

function App() {
  const [view, setView] = useState<'2d' | '3d'>('3d')
  const [isConnected, setIsConnected] = useState(false)
  const [simClient, setSimClient] = useState<SimBridgeClient | null>(null)
  // Lazy components live in STATE so a fresh instance can be minted (a
  // rejected lazy caches its rejection; a new lazy re-runs the import).
  const [Lazy3D, setLazy3D] = useState(() => lazy(load3D))
  const [Lazy2D, setLazy2D] = useState(() => lazy(load2D))

  // Explicit view selection (audit amendment): switching TO a view mints a
  // fresh lazy for the TARGET, so a chunk import that failed earlier is
  // retried on entry — without an unconditional effect (no first-load
  // churn: the slot remounts on switch anyway, and a successfully loaded
  // module resolves instantly from the module cache). Clicking the
  // already-active view is a NO-OP: no remount, no reload.
  const selectView = (target: '2d' | '3d') => {
    if (target === view) return
    if (target === '3d') setLazy3D(() => lazy(load3D))
    else setLazy2D(() => lazy(load2D))
    setView(target)
  }

  // Predictable focus recovery (Package AK): after a successful Retry the
  // Retry button unmounts, which would silently drop keyboard focus on
  // <body>. The active view region (tabIndex=-1) receives focus instead —
  // announced by its aria-label, stealing nothing during ordinary lazy
  // loading (this runs only from the user-initiated Retry).
  const viewRegionRef = useRef<HTMLElement | null>(null)
  const focusViewRegionAfterRetry = () => {
    requestAnimationFrame(() => viewRegionRef.current?.focus())
  }

  useEffect(() => {
    const client = new SimBridgeClient(WS_URL)
    
    client.on('connected', () => setIsConnected(true))
    client.on('disconnected', () => setIsConnected(false))
    
    setSimClient(client)
    client.connect()

    return () => {
      client.disconnect()
    }
  }, [])

  return (
    <div className="app-container">
      <div className="controls">
        <button aria-pressed={view === '2d'} onClick={() => selectView('2d')}>2D View</button>
        <button aria-pressed={view === '3d'} onClick={() => selectView('3d')}>3D View</button>
      </div>

      <EventFeed simClient={simClient} />
      <ConnectionBadge isConnected={isConnected} />

      {/* Each rendered view sits in a labelled region landmark. The wrapper
          mirrors the flex slot the view roots already expect (a flex:1 child
          of the column-flex .app-container) and is itself a flex container,
          so the view root's own flex:1 fills it and child canvas sizing is
          unchanged. minHeight/minWidth 0 keep flex overflow semantics.
          ViewErrorBoundary guards ONLY the replaceable view inside the
          region: a view render exception shows an accessible fallback there
          while the shell (controls, feed, badge) stays mounted; switching
          views remounts a fresh boundary. */}
      {/* The key is load-bearing: both branches are same-type elements in
          the same tree position, so WITHOUT it React reconciles them as one
          component and a failed boundary's state would survive the switch.
          Distinct keys force a remount — a fresh boundary per view. */}
      {view === '3d' ? (
        <section
          key="view-3d"
          ref={viewRegionRef}
          tabIndex={-1}
          role="region"
          aria-label="3D network view"
          style={{ flex: 1, display: 'flex', position: 'relative', minHeight: 0, minWidth: 0 }}
        >
          <ViewErrorBoundary
            viewLabel="3D network view"
            onRetry={() => {
              setLazy3D(() => lazy(load3D))
              focusViewRegionAfterRetry()
            }}
          >
            {/* The transient loading status is scoped inside the active
                region; steady-state keeps the badge as the only status
                region. */}
            <Suspense
              fallback={
                <div role="status" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}>
                  Loading 3D network view…
                </div>
              }
            >
              <Lazy3D simClient={simClient} />
            </Suspense>
          </ViewErrorBoundary>
        </section>
      ) : (
        <section
          key="view-2d"
          ref={viewRegionRef}
          tabIndex={-1}
          role="region"
          aria-label="2D network view"
          style={{ flex: 1, display: 'flex', position: 'relative', minHeight: 0, minWidth: 0 }}
        >
          <ViewErrorBoundary
            viewLabel="2D network view"
            onRetry={() => {
              setLazy2D(() => lazy(load2D))
              focusViewRegionAfterRetry()
            }}
          >
            <Suspense
              fallback={
                <div role="status" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}>
                  Loading 2D network view…
                </div>
              }
            >
              <Lazy2D simClient={simClient} />
            </Suspense>
          </ViewErrorBoundary>
        </section>
      )}
    </div>
  )
}

export default App