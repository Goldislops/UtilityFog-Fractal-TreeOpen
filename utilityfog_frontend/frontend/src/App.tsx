import { useState, useEffect } from 'react'
import NetworkView3D from './viz3d/NetworkView3D'
import NetworkView2D from './components/NetworkView2D'
import ConnectionBadge from './components/ConnectionBadge'
import EventFeed from './components/EventFeed'
import { SimBridgeClient } from './ws/SimBridgeClient'

// Robust WS URL computation
const envUrl = (import.meta as any).env?.VITE_WS_URL as string | undefined;

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

      {/* display:contents keeps these accessibility wrappers out of the
          .app-container flex layout — the view roots stay direct flex
          children, so rendering/styling is unchanged. */}
      {view === '3d' ? (
        <section role="region" aria-label="3D network view" style={{ display: 'contents' }}>
          <NetworkView3D simClient={simClient} />
        </section>
      ) : (
        <section role="region" aria-label="2D network view" style={{ display: 'contents' }}>
          <NetworkView2D simClient={simClient} />
        </section>
      )}
    </div>
  )
}

export default App