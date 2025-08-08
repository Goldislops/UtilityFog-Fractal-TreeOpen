import React, { createContext, useContext, useEffect, useCallback } from 'react';
import useWebSocket, { ReadyState } from 'react-use-websocket';
import { useSimulation } from './SimulationContext';

// WebSocket URL - adjust if your backend is running on a different port
const WS_URL = 'ws://localhost:8002/ws';

const WebSocketContext = createContext();

export const WebSocketProvider = ({ children }) => {
  const simulation = useSimulation();
  
  // WebSocket connection
  const {
    sendMessage,
    sendJsonMessage,
    lastMessage,
    lastJsonMessage,
    readyState,
    getWebSocket
  } = useWebSocket(WS_URL, {
    onOpen: () => {
      console.log('🔌 WebSocket connected');
      simulation.setConnectionStatus(true);
      
      // Send initial ping
      sendJsonMessage({
        type: 'ping',
        timestamp: Date.now()
      });
    },
    onClose: () => {
      console.log('🔌 WebSocket disconnected');
      simulation.setConnectionStatus(false);
    },
    onError: (event) => {
      console.error('🔌 WebSocket error:', event);
      simulation.setError('WebSocket connection error');
    },
    shouldReconnect: (closeEvent) => {
      // Automatically reconnect on connection loss
      console.log('🔄 Attempting to reconnect WebSocket...');
      return true;
    },
    reconnectAttempts: 10,
    reconnectInterval: 3000,
    onReconnectStop: (numAttempts) => {
      console.error(`🔌 Failed to reconnect after ${numAttempts} attempts`);
      simulation.setError('Failed to establish WebSocket connection');
    }
  });
  
  // Handle incoming messages
  useEffect(() => {
    if (lastJsonMessage) {
      handleMessage(lastJsonMessage);
    }
  }, [lastJsonMessage]);
  
  const handleMessage = useCallback((message) => {
    console.log('📨 WebSocket message:', message.type);
    
    try {
      switch (message.type) {
        case 'initial_state':
          console.log('🔄 Setting initial simulation state');
          simulation.setInitialState({
            config: message.config,
            network: message.network,
            positions: message.positions,
            agents: message.agents
          });
          break;
        
        case 'step_update':
          simulation.updateStep(message.data);
          break;
        
        case 'simulation_started':
          console.log('🚀 Simulation started');
          simulation.setSimulationStatus(true);
          simulation.clearError();
          break;
        
        case 'simulation_stopped':
          console.log('⏹️  Simulation stopped');
          simulation.setSimulationStatus(false);
          break;
        
        case 'simulation_complete':
          console.log('🎯 Simulation completed');
          simulation.setSimulationStatus(false);
          // Update final metrics
          if (message.final_stats) {
            simulation.updateMetrics(message.final_stats);
          }
          break;
        
        case 'config_updated':
          console.log('🔧 Configuration updated');
          simulation.updateConfig(message.updates);
          break;
        
        case 'error':
          console.error('❌ Simulation error:', message.message);
          simulation.setError(message.message);
          simulation.setSimulationStatus(false);
          break;
        
        case 'pong':
          // Handle ping/pong for connection health
          break;
        
        default:
          console.warn('🔔 Unknown message type:', message.type);
      }
    } catch (error) {
      console.error('Error handling WebSocket message:', error);
      simulation.setError('Error processing server message');
    }
  }, [simulation]);
  
  // Connection status
  const connectionStatus = {
    [ReadyState.CONNECTING]: 'Connecting',
    [ReadyState.OPEN]: 'Open',
    [ReadyState.CLOSING]: 'Closing',
    [ReadyState.CLOSED]: 'Closed',
    [ReadyState.UNINSTANTIATED]: 'Uninstantiated',
  }[readyState];
  
  // WebSocket actions
  const actions = {
    // Start simulation with configuration
    startSimulation: useCallback((config = null) => {
      const finalConfig = config || simulation.config;
      console.log('🚀 Starting simulation with config:', finalConfig);
      
      sendJsonMessage({
        type: 'start_simulation',
        config: finalConfig
      });
    }, [sendJsonMessage, simulation.config]),
    
    // Stop current simulation
    stopSimulation: useCallback(() => {
      console.log('⏹️  Stopping simulation');
      sendJsonMessage({
        type: 'stop_simulation'
      });
    }, [sendJsonMessage]),
    
    // Update configuration in real-time
    updateConfiguration: useCallback((updates) => {
      console.log('🔧 Updating configuration:', updates);
      
      // Update local state
      simulation.updateConfig(updates);
      
      // Send to server
      sendJsonMessage({
        type: 'update_config',
        updates: updates
      });
    }, [sendJsonMessage, simulation]),
    
    // Send ping to server
    ping: useCallback(() => {
      sendJsonMessage({
        type: 'ping',
        timestamp: Date.now()
      });
    }, [sendJsonMessage]),
    
    // Get connection info
    getConnectionInfo: useCallback(() => {
      return {
        readyState,
        connectionStatus,
        isConnected: readyState === ReadyState.OPEN,
        url: WS_URL
      };
    }, [readyState, connectionStatus])
  };
  
  // Auto-ping every 30 seconds to keep connection alive
  useEffect(() => {
    if (readyState === ReadyState.OPEN) {
      const pingInterval = setInterval(() => {
        actions.ping();
      }, 30000);
      
      return () => clearInterval(pingInterval);
    }
  }, [readyState, actions.ping]);
  
  const value = {
    // WebSocket state
    readyState,
    connectionStatus,
    isConnected: readyState === ReadyState.OPEN,
    
    // Raw WebSocket functions
    sendMessage,
    sendJsonMessage,
    lastMessage,
    lastJsonMessage,
    getWebSocket,
    
    // High-level actions
    ...actions
  };
  
  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider');
  }
  return context;
};

export default WebSocketContext;