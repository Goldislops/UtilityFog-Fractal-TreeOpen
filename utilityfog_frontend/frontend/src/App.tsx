import { useEffect, useState } from 'react';
import { SimBridgeClient, SimBridgeMessage, InitStateMessage } from './ws/SimBridgeClient';
import ConnectionBadge from './components/ConnectionBadge';
import EventFeed from './components/EventFeed';
import NetworkView2D from './components/NetworkView2D';

const WS_URL = (import.meta as any).env?.VITE_WS_URL || 'ws://localhost:8003/ws?run_id=dev';

function App() {
  const [client, setClient] = useState<SimBridgeClient | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'connecting' | 'disconnected'>('disconnected');
  const [lastUpdate, setLastUpdate] = useState<Date>();
  const [messages, setMessages] = useState<SimBridgeMessage[]>([]);
  const [initState, setInitState] = useState<InitStateMessage>();
  const [agentUpdates, setAgentUpdates] = useState<Map<string, any>>(new Map());

  useEffect(() => {
    console.log('🚀 Starting UtilityFog Frontend');
    console.log('🔗 Connecting to:', WS_URL);
    
    const simClient = new SimBridgeClient(WS_URL);
    setClient(simClient);

    // Connection status handlers
    simClient.on('connected', () => {
      setConnectionStatus('connected');
      setLastUpdate(new Date());
    });

    simClient.on('disconnected', () => {
      setConnectionStatus('disconnected');
    });

    simClient.on('error', () => {
      setConnectionStatus('disconnected');
    });

    // Message handlers
    simClient.on('message', (message: SimBridgeMessage) => {
      setMessages(prev => [...prev, message]);
      setLastUpdate(new Date());
    });

    simClient.on('init_state', (message: InitStateMessage) => {
      console.log('🎯 Received init_state:', message.data);
      setInitState(message);
      // Reset agent updates for new simulation
      setAgentUpdates(new Map());
    });

    simClient.on('tick', (message: any) => {
      if (message.data?.agent_updates) {
        setAgentUpdates(prev => {
          const newUpdates = new Map(prev);
          message.data.agent_updates.forEach((update: any) => {
            newUpdates.set(update.id, update);
          });
          return newUpdates;
        });
      }
    });

    // Auto-ping every 30 seconds to keep connection alive
    const pingInterval = setInterval(() => {
      if (simClient.getConnectionStatus() === 'connected') {
        simClient.ping();
      }
    }, 30000);

    return () => {
      clearInterval(pingInterval);
      simClient.disconnect();
    };
  }, []);

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#0f172a',
      color: '#ffffff',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", sans-serif'
    }}>
      {/* Header */}
      <header style={{
        padding: '20px',
        borderBottom: '1px solid #334155',
        backgroundColor: 'rgba(0, 0, 0, 0.5)'
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          maxWidth: '1400px',
          margin: '0 auto'
        }}>
          <div>
            <h1 style={{
              margin: '0 0 8px 0',
              fontSize: '28px',
              fontWeight: '700',
              background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent'
            }}>
              UtilityFog SimBridge
            </h1>
            <p style={{
              margin: 0,
              fontSize: '14px',
              color: '#94a3b8'
            }}>
              Real-time visualization of agent interactions, quantum entanglement, and meme propagation
            </p>
          </div>
          
          <ConnectionBadge 
            status={connectionStatus} 
            lastUpdate={lastUpdate}
          />
        </div>
      </header>

      {/* Main Content */}
      <main style={{
        padding: '20px',
        maxWidth: '1400px',
        margin: '0 auto'
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '20px',
          marginBottom: '20px'
        }}>
          {/* Network View */}
          <div>
            <NetworkView2D
              initState={initState}
              agentUpdates={agentUpdates}
              width={600}
              height={400}
            />
          </div>

          {/* Event Feed */}
          <div>
            <EventFeed messages={messages} maxMessages={25} />
          </div>
        </div>

        {/* Stats */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '16px',
          marginTop: '20px'
        }}>
          <div style={{
            backgroundColor: 'rgba(0, 0, 0, 0.6)',
            border: '1px solid #374151',
            borderRadius: '8px',
            padding: '16px',
            textAlign: 'center'
          }}>
            <div style={{ fontSize: '24px', fontWeight: '700', color: '#10b981' }}>
              {connectionStatus === 'connected' ? 'ONLINE' : 'OFFLINE'}
            </div>
            <div style={{ fontSize: '12px', color: '#6b7280' }}>System Status</div>
          </div>

          <div style={{
            backgroundColor: 'rgba(0, 0, 0, 0.6)',
            border: '1px solid #374151',
            borderRadius: '8px',
            padding: '16px',
            textAlign: 'center'
          }}>
            <div style={{ fontSize: '24px', fontWeight: '700', color: '#667eea' }}>
              {messages.length}
            </div>
            <div style={{ fontSize: '12px', color: '#6b7280' }}>Total Events</div>
          </div>

          <div style={{
            backgroundColor: 'rgba(0, 0, 0, 0.6)',
            border: '1px solid #374151',
            borderRadius: '8px',
            padding: '16px',
            textAlign: 'center'
          }}>
            <div style={{ fontSize: '24px', fontWeight: '700', color: '#f59e0b' }}>
              {initState?.data.nodes.length || 0}
            </div>
            <div style={{ fontSize: '12px', color: '#6b7280' }}>Active Agents</div>
          </div>

          <div style={{
            backgroundColor: 'rgba(0, 0, 0, 0.6)',
            border: '1px solid #374151',
            borderRadius: '8px',
            padding: '16px',
            textAlign: 'center'
          }}>
            <div style={{ fontSize: '24px', fontWeight: '700', color: '#8b5cf6' }}>
              {agentUpdates.size}
            </div>
            <div style={{ fontSize: '12px', color: '#6b7280' }}>Agent Updates</div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer style={{
        padding: '20px',
        textAlign: 'center',
        borderTop: '1px solid #334155',
        color: '#64748b',
        fontSize: '12px',
        marginTop: '40px'
      }}>
        UtilityFog Fractal Network • Connected to {WS_URL}
      </footer>
    </div>
  );
}

export default App;