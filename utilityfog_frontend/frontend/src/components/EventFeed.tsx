import { useState, useEffect, useRef } from 'react'
import { SimBridgeClient } from '../ws/SimBridgeClient'

interface EventFeedProps {
  simClient: SimBridgeClient | null
}

// The four subscription channels this feed renders. The channel is captured
// at subscription time and displayed as the event's type — a payload's own
// `type` field can never spoof the channel label.
const FEED_CHANNELS = [
  'simulation_event',
  'network_update',
  'node_update',
  'edge_update',
] as const
type FeedChannel = (typeof FEED_CHANNELS)[number]

interface FeedEntry {
  // Stable local identifier (monotonic per mounted feed) — the React key.
  // Never the rendered array index, which shifts as entries prepend/expire.
  id: number
  channel: FeedChannel
  timestamp: number
  // Serialized exactly once, at insert time, through the bounded helper.
  preview: string
}

const MAX_EVENTS = 50
const PREVIEW_CHARS = 100

// Bounded, serialize-once preview: COMPACT JSON. The rendering div collapses
// whitespace, so pretty-printing spent part of the 100-character budget on
// formatting the user never saw — the cap now applies to the exact string
// rendered, with the ellipsis appended only when truncated. String payloads
// stay JSON-quoted (deliberate, test-locked): the preview shows the JSON
// value, so "5" and 5 stay distinguishable and behavior matches the feed's
// historical stringify-everything contract. Every payload enters through
// JSON.parse in SimBridgeClient, so circular structures cannot occur; the
// catch is a bounded last resort and never hides ordinary valid payloads.
function formatPreview(data: unknown): string {
  try {
    const full = JSON.stringify(data)
    if (full === undefined) return String(data)
    return full.length > PREVIEW_CHARS ? `${full.slice(0, PREVIEW_CHARS)}...` : full
  } catch {
    return '[unserializable payload]'
  }
}

export default function EventFeed({ simClient }: EventFeedProps) {
  const [events, setEvents] = useState<FeedEntry[]>([])
  const nextIdRef = useRef(0)

  useEffect(() => {
    if (!simClient) return

    const subscriptions = FEED_CHANNELS.map((channel) => {
      const handler = (payload?: unknown) => {
        const entry: FeedEntry = {
          id: nextIdRef.current++,
          channel,
          timestamp: Date.now(),
          preview: formatPreview(payload),
        }
        // Newest first; hold at most MAX_EVENTS.
        setEvents(prev => [entry, ...prev.slice(0, MAX_EVENTS - 1)])
      }
      simClient.on(channel, handler)
      return { channel, handler }
    })

    return () => {
      subscriptions.forEach(({ channel, handler }) => simClient.off(channel, handler))
    }
  }, [simClient])

  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString()
  }

  const getEventColor = (channel: FeedChannel) => {
    switch (channel) {
      case 'node_update': return '#3b82f6'
      case 'edge_update': return '#10b981'
      case 'network_update': return '#f59e0b'
      case 'simulation_event': return '#8b5cf6'
    }
  }

  return (
    <div className="event-feed">
      <h3 style={{ margin: '0 0 10px 0', color: 'white', fontSize: '16px' }}>
        Event Feed
      </h3>
      {/* role="log" (implicitly polite live region): newly inserted events
          are announced without turning the whole app into a live region. */}
      <div role="log" aria-label="Event feed" style={{ maxHeight: '350px', overflowY: 'auto' }}>
        {events.length === 0 ? (
          <div style={{ color: '#9ca3af', fontStyle: 'italic' }}>
            No events yet...
          </div>
        ) : (
          events.map((event) => (
            <div
              key={event.id}
              data-event-channel={event.channel}
              style={{
                padding: '8px',
                marginBottom: '6px',
                backgroundColor: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
                borderLeft: `3px solid ${getEventColor(event.channel)}`,
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
                    color: getEventColor(event.channel),
                    fontSize: '12px',
                    fontWeight: '600',
                  }}
                >
                  {event.channel}
                </span>
                <span style={{ color: '#9ca3af', fontSize: '10px' }}>
                  {formatTime(event.timestamp)}
                </span>
              </div>
              {/* React renders this as text — payload content is never
                  interpreted as markup. */}
              <div style={{ color: 'white', fontSize: '11px' }}>
                {event.preview}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
