/// <reference types="vite/client" />
import { useState, useEffect } from 'react'
import NetworkView3D from './viz3d/NetworkView3D'
import NetworkView2D from './components/NetworkView2D'
import ConnectionBadge from './components/ConnectionBadge'
import EventFeed from './components/EventFeed'
import ViewErrorBoundary from './components/ViewErrorBoundary'
import { SimBridgeClient } from './ws/SimBridgeClient'

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
        <button aria-pressed={view === '2d'} onClick={() => setView('2d')}>2D View</button>
        <button aria-pressed={view === '3d'} onClick={() => setView('3d')}>3D View</button>
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
          role="region"
          aria-label="3D network view"
          style={{ flex: 1, display: 'flex', position: 'relative', minHeight: 0, minWidth: 0 }}
        >
          <ViewErrorBoundary viewLabel="3D network view">
            <NetworkView3D simClient={simClient} />
          </ViewErrorBoundary>
        </section>
      ) : (
        <section
          key="view-2d"
          role="region"
          aria-label="2D network view"
          style={{ flex: 1, display: 'flex', position: 'relative', minHeight: 0, minWidth: 0 }}
        >
          <ViewErrorBoundary viewLabel="2D network view">
            <NetworkView2D simClient={simClient} />
          </ViewErrorBoundary>
        </section>
      )}
    </div>
  )
}

export default App