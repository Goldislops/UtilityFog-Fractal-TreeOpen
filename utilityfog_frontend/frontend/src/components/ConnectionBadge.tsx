interface ConnectionBadgeProps {
  isConnected: boolean
}

export default function ConnectionBadge({ isConnected }: ConnectionBadgeProps) {
  return (
    <div className="connection-badge">
      {/* role="status" is an implicitly polite live region; aria-atomic
          makes each announcement the whole current state, never a diff. */}
      <div
        role="status"
        aria-atomic="true"
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
        {/* Purely decorative indicator — hidden from accessibility APIs.
            The pulse lives in a class so the reduced-motion media query
            below can suppress it. */}
        <div
          aria-hidden="true"
          className={isConnected ? 'connection-badge-dot connection-badge-dot--pulsing' : 'connection-badge-dot'}
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: 'white',
          }}
        />
        {isConnected ? 'Connected' : 'Disconnected'}
      </div>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        .connection-badge-dot--pulsing {
          animation: pulse 2s infinite;
        }
        @media (prefers-reduced-motion: reduce) {
          .connection-badge-dot--pulsing {
            animation: none;
          }
        }
      `}</style>
    </div>
  )
}
