import React from 'react';
import { SimBridgeMessage, EventMessage, TickMessage, StatsMessage } from '../ws/SimBridgeClient';

interface EventFeedProps {
  messages: SimBridgeMessage[];
  maxMessages?: number;
}

const EventFeed: React.FC<EventFeedProps> = ({ messages, maxMessages = 20 }) => {
  const recentMessages = messages.slice(-maxMessages).reverse();

  const formatMessage = (message: SimBridgeMessage) => {
    const time = new Date(message.timestamp || Date.now()).toLocaleTimeString();
    
    switch (message.type) {
      case 'init_state':
        return `${time} - INIT: ${message.data?.nodes?.length || 0} agents, ${message.data?.edges?.length || 0} edges`;
      
      case 'tick':
        const tickMsg = message as TickMessage;
        return `${time} - TICK: Step ${tickMsg.data.step}, ${tickMsg.data.agent_updates?.length || 0} updates`;
      
      case 'event':
        const eventMsg = message as EventMessage;
        const eventData = eventMsg.data;
        if (eventData.event_type === 'ENTANGLEMENT') {
          return `${time} - ENTANGLEMENT: ${eventData.data.source} ⟷ ${eventData.data.target} (${(eventData.data.strength || 0).toFixed(2)})`;
        } else if (eventData.event_type === 'MEME_SPREAD') {
          return `${time} - MEME_SPREAD: ${eventData.data.source} → ${eventData.data.targets?.length || 0} agents`;
        }
        return `${time} - EVENT: ${eventData.event_type}`;
      
      case 'stats':
        const statsMsg = message as StatsMessage;
        return `${time} - STATS: ${statsMsg.data.stats.active_agents} agents, E:${statsMsg.data.stats.average_energy.toFixed(2)}`;
      
      case 'done':
        return `${time} - SIMULATION COMPLETE`;
      
      case 'error':
        return `${time} - ERROR: ${message.data?.error || 'Unknown error'}`;
      
      default:
        return `${time} - ${message.type.toUpperCase()}`;
    }
  };

  const getMessageColor = (message: SimBridgeMessage) => {
    switch (message.type) {
      case 'init_state': return '#667eea';
      case 'tick': return '#6b7280';
      case 'event': 
        if (message.data?.event_type === 'ENTANGLEMENT') return '#8b5cf6';
        if (message.data?.event_type === 'MEME_SPREAD') return '#f59e0b';
        return '#06b6d4';
      case 'stats': return '#10b981';
      case 'done': return '#059669';
      case 'error': return '#ef4444';
      default: return '#9ca3af';
    }
  };

  return (
    <div style={{
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      border: '1px solid #374151',
      borderRadius: '8px',
      padding: '16px',
      height: '300px',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }}>
      <h3 style={{
        margin: '0 0 12px 0',
        fontSize: '16px',
        fontWeight: '600',
        color: '#ffffff'
      }}>
        Live Event Feed
      </h3>
      
      <div style={{
        flex: 1,
        overflow: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px'
      }}>
        {recentMessages.length > 0 ? (
          recentMessages.map((message, index) => (
            <div
              key={`${message.type}-${message.timestamp}-${index}`}
              style={{
                fontSize: '12px',
                fontFamily: 'monospace',
                color: getMessageColor(message),
                padding: '4px 8px',
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
                borderRadius: '4px',
                borderLeft: `2px solid ${getMessageColor(message)}`
              }}
            >
              {formatMessage(message)}
            </div>
          ))
        ) : (
          <div style={{
            color: '#6b7280',
            fontSize: '14px',
            textAlign: 'center',
            marginTop: '40px'
          }}>
            No events yet. Connect to SimBridge to see live data.
          </div>
        )}
      </div>
      
      {messages.length > maxMessages && (
        <div style={{
          fontSize: '11px',
          color: '#6b7280',
          textAlign: 'center',
          marginTop: '8px'
        }}>
          Showing last {maxMessages} of {messages.length} events
        </div>
      )}
    </div>
  );
};

export default EventFeed;