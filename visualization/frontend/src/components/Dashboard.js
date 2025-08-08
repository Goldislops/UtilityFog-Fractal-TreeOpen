import React from 'react';
import { useSimulation } from '../contexts/SimulationContext';
import { useWebSocket } from '../contexts/WebSocketContext';

const Dashboard = () => {
  const {
    config,
    updateConfig,
    canStart,
    canStop,
    isRunning,
    isConnected,
    error
  } = useSimulation();
  
  const { 
    startSimulation, 
    stopSimulation, 
    connectionStatus 
  } = useWebSocket();
  
  // Handle config changes
  const handleConfigChange = (key, value) => {
    const numericValue = parseFloat(value) || 0;
    updateConfig({ [key]: numericValue });
  };
  
  const handleBooleanChange = (key, checked) => {
    updateConfig({ [key]: checked });
  };
  
  return (
    <div className="dashboard">
      <div className="control-group">
        <h3>Simulation Control</h3>
        
        {/* Connection Status */}
        <div className="control-row">
          <div className="control-label">Connection</div>
          <div className={`control-value ${isConnected ? 'text-green-400' : 'text-red-400'}`}>
            {connectionStatus}
          </div>
        </div>
        
        {/* Error Display */}
        {error && (
          <div className="control-row">
            <div className="text-red-400 text-sm">{error}</div>
          </div>
        )}
        
        {/* Start/Stop Buttons */}
        <div className="control-row">
          <button
            className={`btn ${canStart ? 'btn-success' : 'btn-secondary'}`}
            onClick={() => startSimulation()}
            disabled={!canStart}
            style={{ marginRight: '8px' }}
          >
            {isRunning ? '● Running' : '▶ Start'}
          </button>
          
          <button
            className={`btn ${canStop ? 'btn-danger' : 'btn-secondary'}`}
            onClick={stopSimulation}
            disabled={!canStop}
          >
            ⏹ Stop
          </button>
        </div>
      </div>
      
      <div className="control-group">
        <h3>Agent Configuration</h3>
        
        <div className="control-row">
          <div className="control-label">Agents</div>
          <div className="control-input">
            <input
              type="range"
              min="5"
              max="50"
              value={config.num_agents}
              onChange={(e) => handleConfigChange('num_agents', e.target.value)}
              className="slider"
              disabled={isRunning}
            />
          </div>
          <div className="control-value">{config.num_agents}</div>
        </div>
        
        <div className="control-row">
          <div className="control-label">Generations</div>
          <div className="control-input">
            <input
              type="range"
              min="1"
              max="10"
              value={config.num_generations}
              onChange={(e) => handleConfigChange('num_generations', e.target.value)}
              className="slider"
              disabled={isRunning}
            />
          </div>
          <div className="control-value">{config.num_generations}</div>
        </div>
        
        <div className="control-row">
          <div className="control-label">Max Steps</div>
          <div className="control-input">
            <input
              type="range"
              min="50"
              max="500"
              step="25"
              value={config.max_steps}
              onChange={(e) => handleConfigChange('max_steps', e.target.value)}
              className="slider"
              disabled={isRunning}
            />
          </div>
          <div className="control-value">{config.max_steps}</div>
        </div>
      </div>
      
      <div className="control-group">
        <h3>Evolution Parameters</h3>
        
        <div className="control-row">
          <div className="control-label">Mutation Rate</div>
          <div className="control-input">
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={config.mutation_rate}
              onChange={(e) => handleConfigChange('mutation_rate', e.target.value)}
              className="slider"
            />
          </div>
          <div className="control-value">{config.mutation_rate.toFixed(2)}</div>
        </div>
        
        <div className="control-row">
          <div className="control-label">Crossover Rate</div>
          <div className="control-input">
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={config.crossover_rate}
              onChange={(e) => handleConfigChange('crossover_rate', e.target.value)}
              className="slider"
            />
          </div>
          <div className="control-value">{config.crossover_rate.toFixed(2)}</div>
        </div>
      </div>
      
      <div className="control-group">
        <h3>Network Topology</h3>
        
        <div className="control-row">
          <div className="control-label">Network Depth</div>
          <div className="control-input">
            <input
              type="range"
              min="2"
              max="8"
              value={config.network_depth}
              onChange={(e) => handleConfigChange('network_depth', e.target.value)}
              className="slider"
              disabled={isRunning}
            />
          </div>
          <div className="control-value">{config.network_depth}</div>
        </div>
        
        <div className="control-row">
          <div className="control-label">Branching Factor</div>
          <div className="control-input">
            <input
              type="range"
              min="2"
              max="6"
              value={config.branching_factor}
              onChange={(e) => handleConfigChange('branching_factor', e.target.value)}
              className="slider"
              disabled={isRunning}
            />
          </div>
          <div className="control-value">{config.branching_factor}</div>
        </div>
      </div>
      
      <div className="control-group">
        <h3>Quantum Myelin</h3>
        
        <div className="control-row">
          <div className="control-label">Enable Quantum</div>
          <div className="control-input">
            <input
              type="checkbox"
              checked={config.enable_quantum_myelin}
              onChange={(e) => handleBooleanChange('enable_quantum_myelin', e.target.checked)}
              disabled={isRunning}
            />
          </div>
        </div>
        
        <div className="control-row">
          <div className="control-label">Entanglement Threshold</div>
          <div className="control-input">
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={config.entanglement_threshold}
              onChange={(e) => handleConfigChange('entanglement_threshold', e.target.value)}
              className="slider"
            />
          </div>
          <div className="control-value">{config.entanglement_threshold.toFixed(2)}</div>
        </div>
      </div>
      
      <div className="control-group">
        <h3>Visualization</h3>
        
        <div className="control-row">
          <div className="control-label">Step Delay</div>
          <div className="control-input">
            <input
              type="range"
              min="0.01"
              max="2.0"
              step="0.01"
              value={config.step_delay}
              onChange={(e) => handleConfigChange('step_delay', e.target.value)}
              className="slider"
            />
          </div>
          <div className="control-value">{config.step_delay.toFixed(2)}s</div>
        </div>
        
        <div className="control-row">
          <div className="control-label">Show Entanglements</div>
          <div className="control-input">
            <input
              type="checkbox"
              checked={config.show_entanglement_arcs}
              onChange={(e) => handleBooleanChange('show_entanglement_arcs', e.target.checked)}
            />
          </div>
        </div>
        
        <div className="control-row">
          <div className="control-label">Show Meme Propagation</div>
          <div className="control-input">
            <input
              type="checkbox"
              checked={config.show_meme_propagation}
              onChange={(e) => handleBooleanChange('show_meme_propagation', e.target.checked)}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;