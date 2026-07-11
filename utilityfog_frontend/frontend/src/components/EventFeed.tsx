import { useState, useEffect, useMemo, useRef } from 'react'
import type { CSSProperties } from 'react'
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
  // The original parsed payload is retained alongside the preview so JSON
  // export never reconstructs data from the truncated preview.
  payload: unknown
}

const MAX_EVENTS = 50
const PREVIEW_CHARS = 100
const EXPORT_SCHEMA = 'utilityfog.event-feed-export'
const EXPORT_VERSION = 1
// Deterministic, path-safe filename (no separators or unsafe characters).
const EXPORT_FILENAME = 'event-feed-export.json'

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
  const [activeChannels, setActiveChannels] = useState<ReadonlySet<FeedChannel>>(
    () => new Set(FEED_CHANNELS),
  )
  const [search, setSearch] = useState('')
  const [exportError, setExportError] = useState<string | null>(null)
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
          payload,
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

  const toggleChannel = (channel: FeedChannel) => {
    setActiveChannels(prev => {
      const next = new Set(prev)
      if (next.has(channel)) {
        next.delete(channel)
      } else {
        next.add(channel)
      }
      return next
    })
  }

  // Filtering and search change PRESENTATION only — the bounded queue in
  // `events` is untouched. Search is trimmed and case-insensitive over the
  // channel name and the exact rendered preview; the query is treated as a
  // plain string (never markup, a regular expression, or code).
  const query = search.trim().toLowerCase()
  const visible = useMemo(
    () =>
      events.filter(
        e =>
          activeChannels.has(e.channel) &&
          (query === '' || `${e.channel} ${e.preview}`.toLowerCase().includes(query)),
      ),
    [events, activeChannels, query],
  )

  // Deliberate, documented decision: clearing does NOT reset the monotonic
  // id counter — ids only need uniqueness for React keys, and continuing
  // guarantees that across clears. Subscriptions are untouched, so later
  // events still arrive normally.
  const handleClear = () => {
    setEvents([])
    setExportError(null)
  }

  const handleExport = () => {
    try {
      const doc = {
        schema: EXPORT_SCHEMA,
        version: EXPORT_VERSION,
        // Visible (filtered + searched) results only, newest first, carrying
        // the original parsed payloads — never the truncated previews.
        events: visible.map(e => ({
          channel: e.channel,
          timestamp: e.timestamp,
          payload: e.payload,
        })),
      }
      const json = JSON.stringify(doc, null, 2)
      const blob = new Blob([json], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = EXPORT_FILENAME
      anchor.click()
      URL.revokeObjectURL(url)
      setExportError(null)
    } catch {
      // Unreachable through the message path (payloads arrive via
      // JSON.parse), but the guard keeps any failure bounded and visible
      // instead of producing a broken download.
      setExportError('Export failed: the visible events could not be serialized.')
    }
  }

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

  const controlButtonStyle: CSSProperties = {
    fontSize: '10px',
    padding: '2px 6px',
    borderRadius: '4px',
    border: '1px solid rgba(255, 255, 255, 0.3)',
    color: 'white',
    cursor: 'pointer',
  }

  return (
    <div className="event-feed">
      <h3 style={{ margin: '0 0 10px 0', color: 'white', fontSize: '16px' }}>
        Event Feed
      </h3>

      {/* Operations rows: channel filters, search, clear, export. Plain
          controls — deliberately NOT a live region, so the feed's only live
          region remains the role=log list below. */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '6px' }}>
        {FEED_CHANNELS.map(channel => (
          <button
            key={channel}
            aria-pressed={activeChannels.has(channel)}
            onClick={() => toggleChannel(channel)}
            style={{
              ...controlButtonStyle,
              backgroundColor: activeChannels.has(channel)
                ? getEventColor(channel)
                : 'rgba(255, 255, 255, 0.1)',
            }}
          >
            {channel}
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', gap: '4px', marginBottom: '6px' }}>
        <input
          aria-label="Search events"
          placeholder="Search events"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            flex: 1,
            fontSize: '11px',
            padding: '3px 6px',
            borderRadius: '4px',
            border: '1px solid rgba(255, 255, 255, 0.3)',
            backgroundColor: 'rgba(255, 255, 255, 0.1)',
            color: 'white',
          }}
        />
        <button
          onClick={handleClear}
          disabled={events.length === 0}
          style={{ ...controlButtonStyle, backgroundColor: 'rgba(255, 255, 255, 0.1)' }}
        >
          Clear
        </button>
        <button
          onClick={handleExport}
          disabled={visible.length === 0}
          style={{ ...controlButtonStyle, backgroundColor: 'rgba(255, 255, 255, 0.1)' }}
        >
          Export visible JSON
        </button>
      </div>

      {/* Result summary — plain text, deliberately not a live region (no
          second/assertive region nested beside the log). Distinct truthful
          wording for empty feed vs filtered-empty vs populated states. */}
      <div data-testid="feed-summary" style={{ color: '#9ca3af', fontSize: '10px', marginBottom: '6px' }}>
        {events.length === 0
          ? 'No events retained.'
          : `Showing ${visible.length} of ${events.length} events`}
      </div>
      {exportError && (
        <div data-testid="export-error" style={{ color: '#ef4444', fontSize: '10px', marginBottom: '6px' }}>
          {exportError}
        </div>
      )}

      {/* role="log" (implicitly polite live region): newly inserted events
          are announced without turning the whole app into a live region. */}
      <div role="log" aria-label="Event feed" style={{ maxHeight: '350px', overflowY: 'auto' }}>
        {events.length === 0 ? (
          <div style={{ color: '#9ca3af', fontStyle: 'italic' }}>
            No events yet...
          </div>
        ) : visible.length === 0 ? (
          <div style={{ color: '#9ca3af', fontStyle: 'italic' }}>
            No events match the current filters.
          </div>
        ) : (
          visible.map((event) => (
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
