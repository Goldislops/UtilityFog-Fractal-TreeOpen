interface ConnectionBadgeProps {
  isConnected: boolean
}

export default function ConnectionBadge({ isConnected }: ConnectionBadgeProps) {
  return (
    <div className="connection-badge">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '8px 16px',
          backgroundColor: isConnected ? '#10b981' : '#ef4444',
          color: 'white',
          borderRadius: '20px',
          fontSize: '14px',
          fontWeight: '500',
        }}
      >
        <div
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: 'white',
            animation: isConnected ? 'pulse 2s infinite' : 'none',
          }}
        />
        {isConnected ? 'Connected' : 'Disconnected'}
      </div>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  )
}