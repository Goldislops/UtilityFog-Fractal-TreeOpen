import React, { useState } from 'react';
import { useSimBridge } from '../contexts/SimBridgeContext';

const SimulationControls = () => {
  const { connectToRun, disconnect, isRunning, isConnected, error, runId } = useSimBridge();
  const [config, setConfig] = useState({
    num_agents: 10,
    num_generations: 3,
    simulation_steps: 50,
    network_depth: 3,
    branching_factor: 3,
    enable_quantum_myelin: true,
    mutation_rate: 0.1,
    crossover_rate: 0.8,
    initial_memes_per_agent: 2
  });
  
  const [isStarting, setIsStarting] = useState(false);
  
  // API base URL
  const API_BASE = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8003';
  
  const handleStartSimulation = async () => {
    setIsStarting(true);
    
    try {
      // Call API to start simulation
      const response = await fetch(`${API_BASE}/api/sim/start`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(config)
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log('🚀 Simulation started:', data.run_id);
        
        // Connect WebSocket to the new run
        connectToRun(data.run_id);
      } else {
        const errorData = await response.json();
        console.error('Failed to start simulation:', errorData.detail);
      }
    } catch (error) {
      console.error('Error starting simulation:', error);
    } finally {
      setIsStarting(false);
    }
  };
  
  const handleStopSimulation = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/sim/stop`, {
        method: 'POST',
      });
      
      if (response.ok) {
        console.log('⏹️ Simulation stopped');
        disconnect();
      } else {
        const errorData = await response.json();
        console.error('Failed to stop simulation:', errorData.detail);
      }
    } catch (error) {
      console.error('Error stopping simulation:', error);
    }
  };
  
  const handleConfigChange = (key, value) => {
    setConfig(prev => ({
      ...prev,
      [key]: typeof value === 'string' ? parseFloat(value) || 0 : value
    }));
  };
  
  return (
    <div className="simulation-controls bg-gray-900 p-4 rounded-lg border border-gray-600">
      <h2 className="text-xl font-bold text-white mb-4">Simulation Controls</h2>
      
      {/* Connection Status */}
      <div className="mb-4">
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}></div>
          <span className="text-white text-sm">
            {isConnected ? `Connected to ${runId}` : 'Disconnected'}
          </span>
        </div>
        
        {error && (
          <div className="mt-2 text-red-400 text-sm">
            Error: {error}
          </div>
        )}
      </div>
      
      {/* Start/Stop Controls */}
      <div className="mb-6">
        {!isRunning ? (
          <button
            onClick={handleStartSimulation}
            disabled={isStarting}
            className="btn btn-success"
          >
            {isStarting ? '🔄 Starting...' : '▶️ Start Simulation'}
          </button>
        ) : (
          <button
            onClick={handleStopSimulation}
            className="btn btn-danger"
          >
            ⏹️ Stop Simulation
          </button>
        )}
      </div>
      
      {/* Configuration */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-white">Configuration</h3>
        
        <div className="grid grid-cols-1 gap-3">
          <div>
            <label className="block text-sm text-gray-300 mb-1">Agents</label>
            <input
              type="range"
              min="5"
              max="50"
              value={config.num_agents}
              onChange={(e) => handleConfigChange('num_agents', e.target.value)}
              className="slider w-full"
              disabled={isRunning}
            />
            <span className="text-xs text-gray-400">{config.num_agents}</span>
          </div>
          
          <div>
            <label className="block text-sm text-gray-300 mb-1">Simulation Steps</label>
            <input
              type="range"
              min="20"
              max="200"
              step="10"
              value={config.simulation_steps}
              onChange={(e) => handleConfigChange('simulation_steps', e.target.value)}
              className="slider w-full"
              disabled={isRunning}
            />
            <span className="text-xs text-gray-400">{config.simulation_steps}</span>
          </div>
          
          <div>
            <label className="block text-sm text-gray-300 mb-1">Mutation Rate</label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={config.mutation_rate}
              onChange={(e) => handleConfigChange('mutation_rate', e.target.value)}
              className="slider w-full"
              disabled={isRunning}
            />
            <span className="text-xs text-gray-400">{config.mutation_rate.toFixed(2)}</span>
          </div>
          
          <div>
            <label className="block text-sm text-gray-300 mb-1">Network Depth</label>
            <input
              type="range"
              min="2"
              max="6"
              value={config.network_depth}
              onChange={(e) => handleConfigChange('network_depth', e.target.value)}
              className="slider w-full"
              disabled={isRunning}
            />
            <span className="text-xs text-gray-400">{config.network_depth}</span>
          </div>
          
          <div className="flex items-center">
            <input
              type="checkbox"
              checked={config.enable_quantum_myelin}
              onChange={(e) => handleConfigChange('enable_quantum_myelin', e.target.checked)}
              className="mr-2"
              disabled={isRunning}
            />
            <label className="text-sm text-gray-300">Enable Quantum Myelin</label>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SimulationControls;