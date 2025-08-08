import React, { createContext, useContext, useEffect, useCallback, useReducer } from 'react';
import useWebSocketHook, { ReadyState } from 'react-use-websocket';

// SimBridge WebSocket Context for new message schemas
const SimBridgeContext = createContext();

// Initial state
const initialState = {
  // Connection
  isConnected: false,
  runId: null,
  
  // Simulation state
  status: 'idle', // idle, running, completed, error
  currentStep: 0,
  totalSteps: 0,
  
  // Data from init_state
  nodes: [],
  edges: [],
  config: {},
  
  // Real-time events
  recentEvents: [], // ENTANGLEMENT, MEME_SPREAD, ROUTE events
  
  // Statistics
  stats: {
    active_agents: 0,
    total_memes: 0,
    average_energy: 0,
    average_health: 0,
    meme_diversity: 0,
    entanglement_count: 0
  },
  
  // Agent updates (deltas)
  agentUpdates: {},
  
  // Error handling
  error: null,
  lastUpdate: null
};

// Action types
const ActionTypes = {
  SET_CONNECTION: 'SET_CONNECTION',
  SET_RUN_ID: 'SET_RUN_ID',
  INIT_STATE: 'INIT_STATE',
  TICK_UPDATE: 'TICK_UPDATE',
  EVENT_UPDATE: 'EVENT_UPDATE',
  STATS_UPDATE: 'STATS_UPDATE',
  SIMULATION_DONE: 'SIMULATION_DONE',
  SET_ERROR: 'SET_ERROR',
  CLEAR_ERROR: 'CLEAR_ERROR',
  RESET: 'RESET'
};

// Reducer
const simBridgeReducer = (state, action) => {
  switch (action.type) {
    case ActionTypes.SET_CONNECTION:
      return {
        ...state,
        isConnected: action.payload
      };
    
    case ActionTypes.SET_RUN_ID:
      return {
        ...state,
        runId: action.payload
      };
    
    case ActionTypes.INIT_STATE:
      const { nodes, edges, config } = action.payload;
      return {
        ...state,
        nodes: nodes || [],
        edges: edges || [],
        config: config || {},
        status: 'running',
        currentStep: 0,
        totalSteps: config?.simulation_steps || 0,
        agentUpdates: {},
        recentEvents: [],
        error: null
      };
    
    case ActionTypes.TICK_UPDATE:
      const { step, agent_updates } = action.payload;
      
      // Update agent states
      const updatedAgents = { ...state.agentUpdates };
      if (agent_updates) {
        agent_updates.forEach(update => {
          updatedAgents[update.id] = {
            ...updatedAgents[update.id],
            ...update
          };
        });
      }
      
      return {
        ...state,
        currentStep: step || state.currentStep,
        agentUpdates: updatedAgents,
        lastUpdate: Date.now()
      };
    
    case ActionTypes.EVENT_UPDATE:
      const { event_type, data } = action.payload;
      
      const newEvent = {
        id: Math.random().toString(36).substr(2, 9),
        type: event_type,
        data,
        timestamp: Date.now()
      };
      
      // Keep last 50 events
      const updatedEvents = [newEvent, ...state.recentEvents].slice(0, 50);
      
      return {
        ...state,
        recentEvents: updatedEvents
      };
    
    case ActionTypes.STATS_UPDATE:
      return {
        ...state,
        stats: {
          ...state.stats,
          ...action.payload.stats
        }
      };
    
    case ActionTypes.SIMULATION_DONE:
      return {
        ...state,
        status: 'completed'
      };
    
    case ActionTypes.SET_ERROR:
      return {
        ...state,
        error: action.payload,
        status: 'error'
      };
    
    case ActionTypes.CLEAR_ERROR:
      return {
        ...state,
        error: null
      };
    
    case ActionTypes.RESET:
      return {
        ...initialState,
        runId: state.runId,
        isConnected: state.isConnected
      };
    
    default:
      return state;
  }
};

// Provider component
export const SimBridgeProvider = ({ children }) => {
  const [state, dispatch] = useReducer(simBridgeReducer, initialState);
  
  // WebSocket URL construction
  const getWebSocketURL = useCallback((runId) => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = process.env.REACT_APP_BACKEND_URL?.replace(/^https?:\/\//, '') || 'localhost:8003';
    return `${wsProtocol}//${wsHost}/ws?run_id=${runId}`;
  }, []);
  
  // WebSocket connection
  const {
    sendMessage,
    sendJsonMessage,
    lastMessage,
    lastJsonMessage,
    readyState,
    getWebSocket
  } = useWebSocket(
    state.runId ? getWebSocketURL(state.runId) : null,
    {
      onOpen: () => {
        console.log('🔌 SimBridge WebSocket connected');
        dispatch({ type: ActionTypes.SET_CONNECTION, payload: true });
      },
      onClose: () => {
        console.log('🔌 SimBridge WebSocket disconnected');
        dispatch({ type: ActionTypes.SET_CONNECTION, payload: false });
      },
      onError: (event) => {
        console.error('🔌 SimBridge WebSocket error:', event);
        dispatch({ type: ActionTypes.SET_ERROR, payload: 'WebSocket connection error' });
      },
      shouldReconnect: (closeEvent) => {
        return true;
      },
      reconnectAttempts: 5,
      reconnectInterval: 3000,
    },
    !!state.runId // Only connect if we have a runId
  );
  
  // Handle incoming messages
  useEffect(() => {
    if (lastJsonMessage) {
      handleMessage(lastJsonMessage);
    }
  }, [lastJsonMessage]);
  
  const handleMessage = useCallback((message) => {
    console.log('📨 SimBridge message:', message.type, message);
    
    try {
      switch (message.type) {
        case 'connection_confirmed':
          console.log('✅ Connection confirmed for run:', message.run_id);
          break;
        
        case 'init_state':
          dispatch({ type: ActionTypes.INIT_STATE, payload: message.data });
          break;
        
        case 'tick':
          dispatch({ type: ActionTypes.TICK_UPDATE, payload: message.data });
          break;
        
        case 'event':
          dispatch({ type: ActionTypes.EVENT_UPDATE, payload: message.data });
          break;
        
        case 'stats':
          dispatch({ type: ActionTypes.STATS_UPDATE, payload: message.data });
          break;
        
        case 'done':
          dispatch({ type: ActionTypes.SIMULATION_DONE, payload: message.data });
          break;
        
        case 'error':
          dispatch({ type: ActionTypes.SET_ERROR, payload: message.data.error || 'Simulation error' });
          break;
        
        case 'pong':
          // Handle ping/pong for connection health
          break;
        
        default:
          console.warn('🔔 Unknown SimBridge message type:', message.type);
      }
    } catch (error) {
      console.error('Error handling SimBridge message:', error);
      dispatch({ type: ActionTypes.SET_ERROR, payload: 'Error processing server message' });
    }
  }, []);
  
  // Actions
  const actions = {
    // Connect to a specific simulation run
    connectToRun: useCallback((runId) => {
      dispatch({ type: ActionTypes.SET_RUN_ID, payload: runId });
      dispatch({ type: ActionTypes.CLEAR_ERROR });
    }, []),
    
    // Disconnect from current run
    disconnect: useCallback(() => {
      dispatch({ type: ActionTypes.SET_RUN_ID, payload: null });
      dispatch({ type: ActionTypes.RESET });
    }, []),
    
    // Send ping to server
    ping: useCallback(() => {
      if (readyState === ReadyState.OPEN) {
        sendJsonMessage({
          type: 'ping',
          timestamp: Date.now()
        });
      }
    }, [sendJsonMessage, readyState]),
    
    // Subscribe to specific event types
    subscribe: useCallback((eventTypes) => {
      if (readyState === ReadyState.OPEN) {
        sendJsonMessage({
          type: 'subscribe',
          event_types: eventTypes
        });
      }
    }, [sendJsonMessage, readyState]),
    
    // Clear error
    clearError: useCallback(() => {
      dispatch({ type: ActionTypes.CLEAR_ERROR });
    }, []),
    
    // Reset state
    reset: useCallback(() => {
      dispatch({ type: ActionTypes.RESET });
    }, [])
  };
  
  // Connection status
  const connectionStatus = {
    [ReadyState.CONNECTING]: 'Connecting',
    [ReadyState.OPEN]: 'Connected',
    [ReadyState.CLOSING]: 'Disconnecting',
    [ReadyState.CLOSED]: 'Disconnected',
    [ReadyState.UNINSTANTIATED]: 'Not Connected',
  }[readyState];
  
  // Auto-ping every 30 seconds
  useEffect(() => {
    if (readyState === ReadyState.OPEN) {
      const pingInterval = setInterval(() => {
        actions.ping();
      }, 30000);
      
      return () => clearInterval(pingInterval);
    }
  }, [readyState, actions.ping]);
  
  // Computed values
  const computed = {
    isConnected: readyState === ReadyState.OPEN,
    connectionStatus,
    hasError: !!state.error,
    isRunning: state.status === 'running',
    isCompleted: state.status === 'completed',
    progress: state.totalSteps > 0 ? (state.currentStep / state.totalSteps) * 100 : 0,
    
    // Get current agent states (combining initial nodes with updates)
    currentAgents: state.nodes.map(node => ({
      ...node,
      ...state.agentUpdates[node.id]
    })),
    
    // Get recent events by type
    getEventsByType: (eventType) => state.recentEvents.filter(e => e.type === eventType),
    
    // Get entanglement events
    entanglements: state.recentEvents
      .filter(e => e.type === 'ENTANGLEMENT')
      .slice(0, 20), // Last 20 entanglements
    
    // Get meme spread events  
    memeSpreads: state.recentEvents
      .filter(e => e.type === 'MEME_SPREAD')
      .slice(0, 20) // Last 20 meme spreads
  };
  
  const value = {
    ...state,
    ...actions,
    ...computed
  };
  
  return (
    <SimBridgeContext.Provider value={value}>
      {children}
    </SimBridgeContext.Provider>
  );
};

// Hook for using the context
export const useSimBridge = () => {
  const context = useContext(SimBridgeContext);
  if (!context) {
    throw new Error('useSimBridge must be used within a SimBridgeProvider');
  }
  return context;
};

export default SimBridgeContext;