import { useState, useEffect } from 'react'
import { SimBridgeClient, SimEvent } from '../ws/SimBridgeClient'

interface EventFeedProps {
  simClient: SimBridgeClient | null
}

export default function EventFeed({ simClient }: EventFeedProps) {
  const [events, setEvents] = useState<SimEvent[]>([])
  const maxEvents = 50

  useEffect(() => {
    if (!simClient) return

    const handleEvent = (eventData: any) => {
      const event: SimEvent = {
        type: eventData.type || 'unknown',
        timestamp: Date.now(),
        data: eventData
      }

      setEvents(prev => [event, ...prev.slice(0, maxEvents - 1)])
    }

    simClient.on('simulation_event', handleEvent)
    simClient.on('network_update', handleEvent)
    simClient.on('node_update', handleEvent)
    simClient.on('edge_update', handleEvent)

    return () => {
      simClient.off('simulation_event', handleEvent)
      simClient.off('network_update', handleEvent)
      simClient.off('node_update', handleEvent)
      simClient.off('edge_update', handleEvent)
    }
  }, [simClient])

  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString()
  }

  const getEventColor = (type: string) => {
    switch (type) {
      case 'node_update': return '#3b82f6'
      case 'edge_update': return '#10b981'
      case 'network_update': return '#f59e0b'
      case 'simulation_event': return '#8b5cf6'
      default: return '#6b7280'
    }
  }

  return (
    <div className="event-feed">
      <h3 style={{ margin: '0 0 10px 0', color: 'white', fontSize: '16px' }}>
        Event Feed
      </h3>
      <div style={{ maxHeight: '350px', overflowY: 'auto' }}>
        {events.length === 0 ? (
          <div style={{ color: '#9ca3af', fontStyle: 'italic' }}>
            No events yet...
          </div>
        ) : (
          events.map((event, index) => (
            <div
              key={index}
              style={{
                padding: '8px',
                marginBottom: '6px',
                backgroundColor: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
                borderLeft: `3px solid ${getEventColor(event.type)}`,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: '4px',
                }}
              >
                <span
                  style={{
                    color: getEventColor(event.type),
                    fontSize: '12px',
                    fontWeight: '600',
                  }}
                >
                  {event.type}
                </span>
                <span style={{ color: '#9ca3af', fontSize: '10px' }}>
                  {formatTime(event.timestamp)}
                </span>
              </div>
              <div style={{ color: 'white', fontSize: '11px' }}>
                {JSON.stringify(event.data, null, 1).slice(0, 100)}
                {JSON.stringify(event.data).length > 100 ? '...' : ''}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}