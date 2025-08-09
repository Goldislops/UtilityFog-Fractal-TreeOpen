import { useState, useEffect } from 'react'
import NetworkView3D from './viz3d/NetworkView3D'
import NetworkView2D from './components/NetworkView2D'
import ConnectionBadge from './components/ConnectionBadge'
import EventFeed from './components/EventFeed'
import { SimBridgeClient } from './ws/SimBridgeClient'

// WS URL resolution (works local + hosted)
const envUrl = (import.meta as any).env?.VITE_WS_URL as string | undefined;

function computeDefaultWsUrl(): string {
  // e.g. http://localhost:8003  -> ws://localhost:8003/ws?run_id=dev
  //      https://XXXX.preview.abacusai.app -> wss://XXXX.preview.abacusai.app/ws?run_id=dev
  const origin = window.location.origin; // http(s)://host[:port]
  const wsOrigin = origin.replace(/^http/, 'ws');
  return `${wsOrigin}/ws?run_id=dev`;
}

const WS_URL = envUrl && !envUrl.startsWith('ws://https://') ? envUrl : computeDefaultWsUrl();

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
        <button onClick={() => setView('2d')}>2D View</button>
        <button onClick={() => setView('3d')}>3D View</button>
      </div>

      <EventFeed simClient={simClient} />
      <ConnectionBadge isConnected={isConnected} />

      {view === '3d' ? (
        <NetworkView3D simClient={simClient} />
      ) : (
        <NetworkView2D simClient={simClient} />
      )}
    </div>
  )
}

export default App