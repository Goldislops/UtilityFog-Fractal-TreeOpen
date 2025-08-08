import React, { useMemo } from 'react';
import { useSimulation } from '../contexts/SimulationContext';
import { useWebSocket } from '../contexts/WebSocketContext';

const StatusBar = () => {
  const {
    isRunning,
    currentStep,
    config,
    agents,
    entanglements,
    memeEvents,
    error,
    lastUpdate
  } = useSimulation();
  
  const { 
    isConnected,
    connectionStatus
  } = useWebSocket();
  
  // Calculate simulation progress
  const progress = useMemo(() => {
    if (!isRunning || config.max_steps === 0) return 0;
    return Math.min((currentStep / config.max_steps) * 100, 100);
  }, [currentStep, config.max_steps, isRunning]);
  
  // Calculate performance metrics
  const performanceMetrics = useMemo(() => {
    const now = Date.now();
    const timeSinceUpdate = lastUpdate ? now - lastUpdate : 0;
    const updateFreq = timeSinceUpdate < 5000 ? 'Live' : `${Math.floor(timeSinceUpdate / 1000)}s ago`;
    
    return {
      fps: isRunning && timeSinceUpdate < 2000 ? '~60fps' : 'Idle',
      updateFreq,
      memoryUsage: `${Math.floor(Math.random() * 50 + 100)}MB` // Simulated for now
    };
  }, [lastUpdate, isRunning]);
  
  // Format time since start
  const formatSimulationTime = () => {
    if (!isRunning) return '00:00';
    
    // Estimate based on steps and step delay
    const estimatedSeconds = currentStep * config.step_delay;
    const minutes = Math.floor(estimatedSeconds / 60);
    const seconds = Math.floor(estimatedSeconds % 60);
    
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  };
  
  return (
    <div className="status-bar">
      {/* Left side - System status */}
      <div className="status-left flex items-center gap-4">
        {/* Connection status */}
        <div className="status-item">
          <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`}></span>
          <span className="status-text">{connectionStatus}</span>
        </div>
        
        {/* Simulation status */}
        <div className="status-item">
          <span className={`status-dot ${isRunning ? 'running' : 'stopped'}`}></span>
          <span className="status-text">
            {isRunning ? 'Simulation Active' : 'Simulation Stopped'}
          </span>
        </div>
        
        {/* Error indicator */}
        {error && (
          <div className="status-item error">
            <span className="status-dot error"></span>
            <span className="status-text" title={error}>Error: {error.slice(0, 30)}...</span>
          </div>
        )}
      </div>
      
      {/* Center - Progress and step info */}
      <div className="status-center flex items-center gap-4">
        {isRunning && (
          <>
            {/* Progress bar */}
            <div className="progress-container">
              <div 
                className="progress-bar" 
                style={{ width: `${progress}%` }}
              />
              <span className="progress-text">{progress.toFixed(1)}%</span>
            </div>
            
            {/* Step counter */}
            <div className="status-item">
              <span className="status-label">Step:</span>
              <span className="status-value">{currentStep}/{config.max_steps}</span>
            </div>
            
            {/* Time elapsed */}
            <div className="status-item">
              <span className="status-label">Time:</span>
              <span className="status-value">{formatSimulationTime()}</span>
            </div>
          </>
        )}
      </div>
      
      {/* Right side - Metrics and performance */}
      <div className="status-right flex items-center gap-4">
        {/* Agent count */}
        <div className="status-item">
          <span className="status-label">Agents:</span>
          <span className="status-value">{agents.length}</span>
        </div>
        
        {/* Active entanglements */}
        <div className="status-item">
          <span className="status-label">Entanglements:</span>
          <span className="status-value">{entanglements.length}</span>
        </div>
        
        {/* Recent meme events */}
        <div className="status-item">
          <span className="status-label">Meme Events:</span>
          <span className="status-value">{memeEvents.length}</span>
        </div>
        
        {/* Performance metrics */}
        <div className="status-item">
          <span className="status-label">Performance:</span>
          <span className="status-value">{performanceMetrics.fps}</span>
        </div>
        
        <div className="status-item">
          <span className="status-label">Updated:</span>
          <span className="status-value">{performanceMetrics.updateFreq}</span>
        </div>
      </div>
      
      {/* Progress styles */}
      <style jsx>{`
        .progress-container {
          position: relative;
          width: 120px;
          height: 8px;
          background: rgba(255, 255, 255, 0.1);
          border-radius: 4px;
          overflow: hidden;
        }
        
        .progress-bar {
          height: 100%;
          background: linear-gradient(90deg, #10b981, #06b6d4);
          border-radius: 4px;
          transition: width 0.3s ease;
        }
        
        .progress-text {
          position: absolute;
          top: -16px;
          right: 0;
          font-size: 10px;
          color: rgba(255, 255, 255, 0.7);
        }
        
        .status-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          display: inline-block;
          margin-right: 6px;
        }
        
        .status-dot.connected {
          background: #10b981;
          box-shadow: 0 0 6px #10b981;
        }
        
        .status-dot.disconnected {
          background: #ef4444;
          box-shadow: 0 0 6px #ef4444;
        }
        
        .status-dot.running {
          background: #06b6d4;
          box-shadow: 0 0 6px #06b6d4;
          animation: pulse 2s infinite;
        }
        
        .status-dot.stopped {
          background: #6b7280;
        }
        
        .status-dot.error {
          background: #f59e0b;
          box-shadow: 0 0 6px #f59e0b;
          animation: pulse 1s infinite;
        }
        
        .status-item {
          display: flex;
          align-items: center;
          font-size: 11px;
        }
        
        .status-item.error .status-text {
          color: #f59e0b;
        }
        
        .status-label {
          color: rgba(255, 255, 255, 0.6);
          margin-right: 4px;
        }
        
        .status-value {
          color: rgba(255, 255, 255, 0.9);
          font-weight: 500;
          font-family: 'Courier New', monospace;
        }
        
        .status-text {
          color: rgba(255, 255, 255, 0.8);
        }
        
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
};

export default StatusBar;