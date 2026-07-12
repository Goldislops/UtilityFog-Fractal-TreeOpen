/// <reference types="vite/client" />
import { useState, useEffect, useLayoutEffect, useRef, lazy } from 'react'
import ConnectionBadge from './components/ConnectionBadge'
import EventFeed from './components/EventFeed'
import ViewErrorBoundary from './components/ViewErrorBoundary'
import { SimBridgeClient } from './ws/SimBridgeClient'
import { probeWebGLSupport } from './viz3d/webglSupport'

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

  // Predictable focus recovery (Package AK, success-aware amendment):
  // after a Retry the old button unmounts, which would silently drop
  // keyboard focus on <body>. Focus moves to the labelled view region
  // ONLY when the boundary reports a successful child commit
  // (onRecovered) — a retry that fails again keeps focus on the new
  // Retry button (boundary-owned), and ordinary lazy loading steals
  // nothing (onRecovered never fires outside a retry cycle).
  const viewRegionRef = useRef<HTMLElement | null>(null)
  const focusViewRegion = () => {
    viewRegionRef.current?.focus()
  }

  // WebGL capability gate (Package AL): probed BEFORE the heavy 3D
  // renderer mounts (and before its chunk is even fetched). null = not
  // yet probed; probing happens at most once per 3D entry — the result
  // is held in state, so switching views or rerendering NEVER re-probes
  // (no probe loop, no log spam). The ONLY re-probe path is the explicit
  // user-paced button in the fallback below. A successful probe does not
  // guarantee Three.js will render — runtime renderer failures still
  // belong to ViewErrorBoundary.
  //
  // useLayoutEffect (amendment): the probe resolves commit-synchronously,
  // BEFORE the browser paints — the 3D region never paints an empty
  // pending frame while a passive effect waits to run.
  const [webglSupport, setWebglSupport] = useState<boolean | null>(null)
  useLayoutEffect(() => {
    if (view === '3d' && webglSupport === null) {
      setWebglSupport(probeWebGLSupport())
    }
  }, [view, webglSupport])

  // Injected reload seam (Package AL amendment): the boundary presents
  // "Reload application" for chunk-load failures and calls back through
  // this — the boundary itself never touches a global.
  const requestReload = () => {
    window.location.reload()
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
      {/* Layout comes from the .view-region CLASS contract (desktop
          min-height 0 for flex overflow semantics; mobile enforces a
          240px floor) — an inline min-height would silently defeat the
          media-query floor, which is exactly the defect this replaced. */}
      {view === '3d' ? (
        <section
          key="view-3d"
          ref={viewRegionRef}
          tabIndex={-1}
          role="region"
          aria-label="3D network view"
          className="view-region"
        >
          {/* The capability gate replaces the renderer INSIDE the region:
              shell, connection, feed and controls live above and stay
              untouched, and no additional SimBridge connection exists on
              this path. */}
          {webglSupport === false ? (
            <div className="webgl-fallback">
              <p>
                The 3D network view is unavailable: this browser or device
                has no usable WebGL support.
              </p>
              <button
                type="button"
                className="webgl-use-2d-button"
                onClick={() => selectView('2d')}
              >
                Use 2D view
              </button>
              <button
                type="button"
                className="webgl-reprobe-button"
                onClick={() => setWebglSupport(probeWebGLSupport())}
              >
                Check 3D support again
              </button>
            </div>
          ) : webglSupport === true ? (
            <ViewErrorBoundary
              viewLabel="3D network view"
              onRetry={() => setLazy3D(() => lazy(load3D))}
              onRecovered={focusViewRegion}
              onReloadRequest={requestReload}
              suspenseFallback={
                /* The transient loading status is scoped inside the active
                   region; steady-state keeps the badge as the only status
                   region. */
                <div role="status" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}>
                  Loading 3D network view…
                </div>
              }
            >
              <Lazy3D simClient={simClient} />
            </ViewErrorBoundary>
          ) : null /* probe pending: resolved by the effect within the same tick */}
        </section>
      ) : (
        <section
          key="view-2d"
          ref={viewRegionRef}
          tabIndex={-1}
          role="region"
          aria-label="2D network view"
          className="view-region"
        >
          <ViewErrorBoundary
            viewLabel="2D network view"
            onRetry={() => setLazy2D(() => lazy(load2D))}
            onRecovered={focusViewRegion}
            onReloadRequest={requestReload}
            suspenseFallback={
              <div role="status" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}>
                Loading 2D network view…
              </div>
            }
          >
            <Lazy2D simClient={simClient} />
          </ViewErrorBoundary>
        </section>
      )}
    </div>
  )
}

export default App