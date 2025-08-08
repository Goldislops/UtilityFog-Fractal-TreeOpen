import React, { createContext, useContext, useReducer, useCallback } from 'react';

// Initial simulation state
const initialState = {
  // Simulation status
  isRunning: false,
  isConnected: false,
  currentStep: 0,
  totalSteps: 100,
  
  // Configuration
  config: {
    num_agents: 10,
    num_generations: 3,
    max_steps: 100,
    mutation_rate: 0.1,
    crossover_rate: 0.8,
    network_depth: 3,
    branching_factor: 3,
    initial_memes_per_agent: 2,
    enable_quantum_myelin: true,
    entanglement_threshold: 0.2,
    step_delay: 0.1,
    show_entanglement_arcs: true,
    show_meme_propagation: true,
    max_entanglements_displayed: 50,
    max_meme_events_displayed: 20
  },
  
  // Network data
  network: {
    nodes: [],
    edges: [],
    stats: {}
  },
  
  // Agent data
  agents: [],
  agentPositions: {},
  
  // Real-time events
  entanglements: [],
  memeEvents: [],
  
  // Metrics
  metrics: {
    totalEntanglements: 0,
    totalMemes: 0,
    averageEnergy: 0,
    averageHealth: 0,
    networkConnectivity: 0
  },
  
  // Timeline data
  timeline: {
    steps: [],
    memeHistory: [],
    entanglementHistory: []
  },
  
  // Error handling
  error: null,
  lastUpdate: null
};

// Action types
const ActionTypes = {
  SET_CONNECTION_STATUS: 'SET_CONNECTION_STATUS',
  SET_SIMULATION_STATUS: 'SET_SIMULATION_STATUS',
  UPDATE_CONFIG: 'UPDATE_CONFIG',
  SET_INITIAL_STATE: 'SET_INITIAL_STATE',
  STEP_UPDATE: 'STEP_UPDATE',
  ADD_ENTANGLEMENT: 'ADD_ENTANGLEMENT',
  ADD_MEME_EVENT: 'ADD_MEME_EVENT',
  UPDATE_AGENTS: 'UPDATE_AGENTS',
  UPDATE_NETWORK: 'UPDATE_NETWORK',
  UPDATE_METRICS: 'UPDATE_METRICS',
  SET_ERROR: 'SET_ERROR',
  CLEAR_ERROR: 'CLEAR_ERROR',
  RESET_SIMULATION: 'RESET_SIMULATION'
};

// Reducer function
const simulationReducer = (state, action) => {
  switch (action.type) {
    case ActionTypes.SET_CONNECTION_STATUS:
      return {
        ...state,
        isConnected: action.payload,
        error: action.payload ? null : state.error
      };
    
    case ActionTypes.SET_SIMULATION_STATUS:
      return {
        ...state,
        isRunning: action.payload
      };
    
    case ActionTypes.UPDATE_CONFIG:
      return {
        ...state,
        config: { ...state.config, ...action.payload }
      };
    
    case ActionTypes.SET_INITIAL_STATE:
      const { config, network, positions, agents } = action.payload;
      return {
        ...state,
        config: config || state.config,
        network: network || state.network,
        agentPositions: positions || state.agentPositions,
        agents: agents || state.agents,
        currentStep: 0,
        entanglements: [],
        memeEvents: [],
        timeline: {
          steps: [],
          memeHistory: [],
          entanglementHistory: []
        }
      };
    
    case ActionTypes.STEP_UPDATE:
      const stepData = action.payload;
      const newStep = stepData.step || state.currentStep + 1;
      
      // Update timeline
      const newTimeline = {
        steps: [...state.timeline.steps, {
          step: newStep,
          timestamp: stepData.timestamp,
          metrics: stepData.metrics || {}
        }].slice(-100), // Keep last 100 steps
        
        memeHistory: [...state.timeline.memeHistory, ...stepData.meme_events || []].slice(-200),
        
        entanglementHistory: [...state.timeline.entanglementHistory, ...stepData.entanglements || []].slice(-200)
      };
      
      return {
        ...state,
        currentStep: newStep,
        timeline: newTimeline,
        lastUpdate: Date.now()
      };
    
    case ActionTypes.ADD_ENTANGLEMENT:
      const entanglement = {
        ...action.payload,
        id: Math.random().toString(36).substr(2, 9),
        createdAt: Date.now()
      };
      
      // Remove old entanglements and add new one
      const filteredEntanglements = state.entanglements.filter(
        e => Date.now() - e.createdAt < 5000 // Keep for 5 seconds
      );
      
      return {
        ...state,
        entanglements: [...filteredEntanglements, entanglement].slice(-state.config.max_entanglements_displayed),
        metrics: {
          ...state.metrics,
          totalEntanglements: state.metrics.totalEntanglements + 1
        }
      };
    
    case ActionTypes.ADD_MEME_EVENT:
      const memeEvent = {
        ...action.payload,
        id: Math.random().toString(36).substr(2, 9),
        createdAt: Date.now()
      };
      
      // Remove old meme events and add new one
      const filteredMemeEvents = state.memeEvents.filter(
        e => Date.now() - e.createdAt < 10000 // Keep for 10 seconds
      );
      
      return {
        ...state,
        memeEvents: [...filteredMemeEvents, memeEvent].slice(-state.config.max_meme_events_displayed)
      };
    
    case ActionTypes.UPDATE_AGENTS:
      const updatedAgents = action.payload;
      
      // Calculate metrics
      const totalAgents = updatedAgents.length;
      const averageEnergy = totalAgents > 0 
        ? updatedAgents.reduce((sum, agent) => sum + (agent.energy || 0), 0) / totalAgents 
        : 0;
      const averageHealth = totalAgents > 0 
        ? updatedAgents.reduce((sum, agent) => sum + (agent.health || 0), 0) / totalAgents 
        : 0;
      const totalActiveMemes = updatedAgents.reduce((sum, agent) => sum + (agent.active_memes || 0), 0);
      
      return {
        ...state,
        agents: updatedAgents,
        metrics: {
          ...state.metrics,
          averageEnergy: Math.round(averageEnergy * 1000) / 1000,
          averageHealth: Math.round(averageHealth * 1000) / 1000,
          totalMemes: totalActiveMemes
        }
      };
    
    case ActionTypes.UPDATE_NETWORK:
      return {
        ...state,
        network: action.payload,
        metrics: {
          ...state.metrics,
          networkConnectivity: action.payload.stats?.connectivity || 0
        }
      };
    
    case ActionTypes.UPDATE_METRICS:
      return {
        ...state,
        metrics: { ...state.metrics, ...action.payload }
      };
    
    case ActionTypes.SET_ERROR:
      return {
        ...state,
        error: action.payload
      };
    
    case ActionTypes.CLEAR_ERROR:
      return {
        ...state,
        error: null
      };
    
    case ActionTypes.RESET_SIMULATION:
      return {
        ...initialState,
        config: state.config, // Keep current config
        isConnected: state.isConnected // Keep connection status
      };
    
    default:
      return state;
  }
};

// Context
const SimulationContext = createContext();

// Provider component
export const SimulationProvider = ({ children }) => {
  const [state, dispatch] = useReducer(simulationReducer, initialState);
  
  // Action creators
  const actions = {
    setConnectionStatus: useCallback((isConnected) => {
      dispatch({ type: ActionTypes.SET_CONNECTION_STATUS, payload: isConnected });
    }, []),
    
    setSimulationStatus: useCallback((isRunning) => {
      dispatch({ type: ActionTypes.SET_SIMULATION_STATUS, payload: isRunning });
    }, []),
    
    updateConfig: useCallback((configUpdates) => {
      dispatch({ type: ActionTypes.UPDATE_CONFIG, payload: configUpdates });
    }, []),
    
    setInitialState: useCallback((initialData) => {
      dispatch({ type: ActionTypes.SET_INITIAL_STATE, payload: initialData });
    }, []),
    
    updateStep: useCallback((stepData) => {
      dispatch({ type: ActionTypes.STEP_UPDATE, payload: stepData });
      
      // Process entanglements
      if (stepData.entanglements) {
        stepData.entanglements.forEach(entanglement => {
          dispatch({ type: ActionTypes.ADD_ENTANGLEMENT, payload: entanglement });
        });
      }
      
      // Process meme events
      if (stepData.meme_events) {
        stepData.meme_events.forEach(event => {
          dispatch({ type: ActionTypes.ADD_MEME_EVENT, payload: event });
        });
      }
      
      // Update agents
      if (stepData.agent_updates) {
        dispatch({ type: ActionTypes.UPDATE_AGENTS, payload: stepData.agent_updates });
      }
    }, []),
    
    updateAgents: useCallback((agents) => {
      dispatch({ type: ActionTypes.UPDATE_AGENTS, payload: agents });
    }, []),
    
    updateNetwork: useCallback((network) => {
      dispatch({ type: ActionTypes.UPDATE_NETWORK, payload: network });
    }, []),
    
    updateMetrics: useCallback((metrics) => {
      dispatch({ type: ActionTypes.UPDATE_METRICS, payload: metrics });
    }, []),
    
    setError: useCallback((error) => {
      dispatch({ type: ActionTypes.SET_ERROR, payload: error });
    }, []),
    
    clearError: useCallback(() => {
      dispatch({ type: ActionTypes.CLEAR_ERROR });
    }, []),
    
    resetSimulation: useCallback(() => {
      dispatch({ type: ActionTypes.RESET_SIMULATION });
    }, [])
  };
  
  // Computed values
  const computed = {
    progress: state.totalSteps > 0 ? (state.currentStep / state.totalSteps) * 100 : 0,
    hasError: !!state.error,
    canStart: state.isConnected && !state.isRunning,
    canStop: state.isConnected && state.isRunning,
    agentCount: state.agents.length,
    activeEntanglements: state.entanglements.length,
    recentMemeEvents: state.memeEvents.length,
    simulationDuration: state.timeline.steps.length > 0 
      ? Date.now() - (state.timeline.steps[0].timestamp * 1000) 
      : 0
  };
  
  const value = {
    ...state,
    ...actions,
    ...computed
  };
  
  return (
    <SimulationContext.Provider value={value}>
      {children}
    </SimulationContext.Provider>
  );
};

// Hook for using the context
export const useSimulation = () => {
  const context = useContext(SimulationContext);
  if (!context) {
    throw new Error('useSimulation must be used within a SimulationProvider');
  }
  return context;
};

export default SimulationContext;