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

export class SimBridgeClient {
  private ws: WebSocket | null = null
  private url: string
  private listeners: Map<string, Set<(data?: any) => void>> = new Map()
  private reconnectInterval = 5000
  private reconnectTimer: number | null = null

  constructor(url: string) {
    this.url = url
  }

  connect(): void {
    try {
      this.ws = new WebSocket(this.url)
      
      this.ws.onopen = () => {
        console.log('Connected to SimBridge')
        this.emit('connected')
        this.clearReconnectTimer()
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          this.handleMessage(data)
        } catch (error) {
          console.error('Error parsing message:', error)
        }
      }

      this.ws.onclose = () => {
        console.log('Disconnected from SimBridge')
        this.emit('disconnected')
        this.scheduleReconnect()
      }

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        this.emit('error', error)
      }
    } catch (error) {
      console.error('Failed to connect:', error)
      this.scheduleReconnect()
    }
  }

  disconnect(): void {
    this.clearReconnectTimer()
    if (this.ws) {
      this.ws.close()
      this.ws = null
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
    this.clearReconnectTimer()
    this.reconnectTimer = window.setTimeout(() => {
      console.log('Attempting to reconnect...')
      this.connect()
    }, this.reconnectInterval)
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

export type { SimEvent, NetworkNode, NetworkEdge }