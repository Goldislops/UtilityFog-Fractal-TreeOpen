// SimBridge WebSocket Client with auto-reconnect and type guards

export interface SimBridgeMessage {
  type: 'init_state' | 'tick' | 'event' | 'stats' | 'done' | 'error' | 'connection_confirmed' | 'pong';
  data?: any;
  timestamp?: number;
}

export interface InitStateMessage extends SimBridgeMessage {
  type: 'init_state';
  data: {
    nodes: Array<{ id: string; [key: string]: any }>;
    edges: Array<{ source: string; target: string; [key: string]: any }>;
    config: Record<string, any>;
  };
}

export interface TickMessage extends SimBridgeMessage {
  type: 'tick';
  data: {
    step: number;
    agent_updates: Array<{ id: string; [key: string]: any }>;
    timestamp: number;
  };
}

export interface EventMessage extends SimBridgeMessage {
  type: 'event';
  data: {
    event_type: 'ENTANGLEMENT' | 'MEME_SPREAD' | 'ROUTE';
    data: Record<string, any>;
    step: number;
    timestamp: number;
  };
}

export interface StatsMessage extends SimBridgeMessage {
  type: 'stats';
  data: {
    step: number;
    stats: {
      active_agents: number;
      total_memes: number;
      average_energy: number;
      average_health: number;
      meme_diversity: number;
      entanglement_count: number;
    };
    timestamp: number;
  };
}

export class SimBridgeClient {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 3000;
  private listeners: Map<string, Set<Function>> = new Map();
  private isConnected = false;

  constructor(url: string) {
    this.url = url;
    this.connect();
  }

  private connect() {
    try {
      console.log(`🔌 Connecting to SimBridge: ${this.url}`);
      this.ws = new WebSocket(this.url);
      
      this.ws.onopen = () => {
        console.log('✅ SimBridge connected');
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.emit('connected');
      };

      this.ws.onmessage = (event) => {
        try {
          const message: SimBridgeMessage = JSON.parse(event.data);
          console.log('📨 SimBridge message:', message.type);
          this.emit('message', message);
          this.emit(message.type, message);
        } catch (error) {
          console.error('❌ Failed to parse message:', error);
        }
      };

      this.ws.onclose = () => {
        console.log('🔌 SimBridge disconnected');
        this.isConnected = false;
        this.emit('disconnected');
        this.handleReconnect();
      };

      this.ws.onerror = (error) => {
        console.error('❌ SimBridge WebSocket error:', error);
        this.emit('error', error);
      };
    } catch (error) {
      console.error('❌ Failed to create WebSocket:', error);
      this.handleReconnect();
    }
  }

  private handleReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      console.log(`🔄 Reconnecting (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${this.reconnectDelay}ms`);
      
      setTimeout(() => {
        this.connect();
      }, this.reconnectDelay);
      
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, 30000); // Max 30s
    } else {
      console.error('❌ Max reconnection attempts reached');
      this.emit('maxReconnectsReached');
    }
  }

  public on(event: string, callback: Function) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(callback);
  }

  public off(event: string, callback: Function) {
    const eventListeners = this.listeners.get(event);
    if (eventListeners) {
      eventListeners.delete(callback);
    }
  }

  private emit(event: string, data?: any) {
    const eventListeners = this.listeners.get(event);
    if (eventListeners) {
      eventListeners.forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error(`❌ Error in event listener for ${event}:`, error);
        }
      });
    }
  }

  public send(message: Record<string, any>) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      console.warn('⚠️ WebSocket not connected, message not sent:', message);
    }
  }

  public ping() {
    this.send({ type: 'ping', timestamp: Date.now() });
  }

  public getConnectionStatus(): 'connected' | 'connecting' | 'disconnected' {
    if (this.isConnected) return 'connected';
    if (this.ws && this.ws.readyState === WebSocket.CONNECTING) return 'connecting';
    return 'disconnected';
  }

  public disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  // Type guards for message validation
  public static isInitState(message: SimBridgeMessage): message is InitStateMessage {
    return message.type === 'init_state' && 
           message.data && 
           Array.isArray(message.data.nodes) &&
           Array.isArray(message.data.edges);
  }

  public static isTick(message: SimBridgeMessage): message is TickMessage {
    return message.type === 'tick' && 
           message.data && 
           typeof message.data.step === 'number';
  }

  public static isEvent(message: SimBridgeMessage): message is EventMessage {
    return message.type === 'event' && 
           message.data && 
           ['ENTANGLEMENT', 'MEME_SPREAD', 'ROUTE'].includes(message.data.event_type);
  }

  public static isStats(message: SimBridgeMessage): message is StatsMessage {
    return message.type === 'stats' && 
           message.data && 
           message.data.stats &&
           typeof message.data.stats.active_agents === 'number';
  }
}