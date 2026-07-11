interface SimEvent {
  type: string
  timestamp: number
  data: any
}

interface NetworkNode {
  id: string
  position: [number, number, number]
  connections: string[]
  status: 'active' | 'inactive' | 'error'
}

interface NetworkEdge {
  id: string
  source: string
  target: string
  strength: number
}

// Lifecycle contract (see tests/simbridge-lifecycle.spec.ts):
//   - connect() enables reconnect intent; it is idempotent while the current
//     socket is CONNECTING or OPEN.
//   - Only the CURRENT socket instance may mutate connection state or
//     schedule a reconnect — every handler checks socket identity, so late
//     callbacks from an obsolete socket are inert.
//   - An unexpected close emits 'disconnected' and schedules at most one
//     reconnect. A successful open clears pending reconnect state.
//   - disconnect() disables reconnect intent, clears any pending reconnect
//     timer, releases the socket BEFORE closing it (so its close callback
//     fails the identity check and can never schedule a reconnect), and
//     emits 'disconnected' synchronously so UI state stays truthful.
//   - A later explicit connect() starts a fresh socket.
export class SimBridgeClient {
  private ws: WebSocket | null = null
  private url: string
  private listeners: Map<string, Set<(data?: any) => void>> = new Map()
  private reconnectInterval: number
  private reconnectTimer: number | null = null
  private shouldReconnect = false

  // reconnectIntervalMs is optional and defaults to the previous fixed
  // 5000ms — existing `new SimBridgeClient(url)` calls are unchanged. Tests
  // inject a short delay for deterministic reconnect timing.
  constructor(url: string, reconnectIntervalMs: number = 5000) {
    this.url = url
    this.reconnectInterval = reconnectIntervalMs
  }

  connect(): void {
    this.shouldReconnect = true
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)
    ) {
      return
    }
    this.clearReconnectTimer()
    this.openSocket()
  }

  disconnect(): void {
    this.shouldReconnect = false
    this.clearReconnectTimer()
    if (this.ws) {
      const socket = this.ws
      // Release before closing: the socket's own close callback then fails
      // the identity check and cannot schedule a reconnect.
      this.ws = null
      socket.close()
      this.emit('disconnected')
    }
  }

  on(event: string, callback: (data?: any) => void): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(callback)
  }

  off(event: string, callback: (data?: any) => void): void {
    this.listeners.get(event)?.delete(callback)
  }

  send(data: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  private openSocket(): void {
    let socket: WebSocket
    try {
      socket = new WebSocket(this.url)
    } catch (error) {
      // Synchronous construction failure (bad scheme, CSP, …): no socket
      // exists, so the client must not keep pointing at a stale one.
      // Surface the failure and retry on the normal schedule while
      // reconnect intent holds — at most one timer, no duplicate sockets.
      this.ws = null
      console.error('Failed to connect:', error)
      this.emit('error', error)
      if (this.shouldReconnect) {
        this.scheduleReconnect()
      }
      return
    }
    this.ws = socket

    socket.onopen = () => {
      if (this.ws !== socket) return
      console.log('Connected to SimBridge')
      this.clearReconnectTimer()
      this.emit('connected')
    }

    socket.onmessage = (event) => {
      if (this.ws !== socket) return
      // Parse inside the catch boundary; dispatch outside it. A listener
      // exception must surface through the page error channel, not be
      // swallowed and mislabelled as a JSON parsing failure.
      let data: any
      try {
        data = JSON.parse(event.data)
      } catch (error) {
        console.error('Error parsing message:', error)
        return
      }
      this.handleMessage(data)
    }

    socket.onclose = () => {
      if (this.ws !== socket) return
      this.ws = null
      console.log('Disconnected from SimBridge')
      this.emit('disconnected')
      if (this.shouldReconnect) {
        this.scheduleReconnect()
      }
    }

    socket.onerror = (error) => {
      if (this.ws !== socket) return
      console.error('WebSocket error:', error)
      this.emit('error', error)
    }
  }

  private handleMessage(data: any): void {
    switch (data.type) {
      case 'simulation_event':
        this.emit('simulation_event', data.payload)
        break
      case 'network_update':
        this.emit('network_update', data.payload)
        break
      case 'node_update':
        this.emit('node_update', data.payload)
        break
      case 'edge_update':
        this.emit('edge_update', data.payload)
        break
      default:
        console.log('Unknown message type:', data.type)
    }
  }

  private emit(event: string, data?: any): void {
    this.listeners.get(event)?.forEach(callback => callback(data))
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) {
      return
    }
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      if (!this.shouldReconnect) return
      console.log('Attempting to reconnect...')
      this.openSocket()
    }, this.reconnectInterval)
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

export type { SimEvent, NetworkNode, NetworkEdge }
