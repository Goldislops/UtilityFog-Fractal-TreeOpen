import React from 'react';

interface ConnectionBadgeProps {
  status: 'connected' | 'connecting' | 'disconnected';
  lastUpdate?: Date;
}

const ConnectionBadge: React.FC<ConnectionBadgeProps> = ({ status, lastUpdate }) => {
  const getStatusColor = () => {
    switch (status) {
      case 'connected': return '#10b981';
      case 'connecting': return '#f59e0b';
      case 'disconnected': return '#ef4444';
    }
  };

  const getStatusText = () => {
    switch (status) {
      case 'connected': return 'Connected';
      case 'connecting': return 'Connecting...';
      case 'disconnected': return 'Disconnected';
    }
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      padding: '8px 12px',
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      border: `1px solid ${getStatusColor()}`,
      borderRadius: '6px',
      fontSize: '14px',
      fontWeight: '500'
    }}>
      <div style={{
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        backgroundColor: getStatusColor(),
        animation: status === 'connecting' ? 'pulse 2s infinite' : undefined
      }} />
      <span style={{ color: getStatusColor() }}>
        {getStatusText()}
      </span>
      {lastUpdate && status === 'connected' && (
        <span style={{ 
          color: '#6b7280', 
          fontSize: '12px',
          marginLeft: '4px'
        }}>
          {lastUpdate.toLocaleTimeString()}
        </span>
      )}
      
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
};

export default ConnectionBadge;