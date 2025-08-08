import React, { useMemo } from 'react';
import { useSimulation } from '../contexts/SimulationContext';

const AgentMetrics = () => {
  const {
    agents,
    metrics,
    entanglements,
    memeEvents,
    currentStep
  } = useSimulation();
  
  // Calculate real-time metrics
  const liveMetrics = useMemo(() => {
    const totalAgents = agents.length;
    
    if (totalAgents === 0) {
      return {
        totalAgents: 0,
        averageEnergy: 0,
        averageHealth: 0,
        totalActiveMemes: 0,
        activeEntanglements: 0,
        recentMemeEvents: 0
      };
    }
    
    const totalEnergy = agents.reduce((sum, agent) => sum + (agent.energy || 0), 0);
    const totalHealth = agents.reduce((sum, agent) => sum + (agent.health || 1), 0);
    const totalActiveMemes = agents.reduce((sum, agent) => sum + (agent.active_memes || 0), 0);
    
    return {
      totalAgents,
      averageEnergy: totalEnergy / totalAgents,
      averageHealth: totalHealth / totalAgents,
      totalActiveMemes,
      activeEntanglements: entanglements.length,
      recentMemeEvents: memeEvents.length
    };
  }, [agents, entanglements, memeEvents]);
  
  // Energy distribution analysis
  const energyDistribution = useMemo(() => {
    if (agents.length === 0) return { high: 0, medium: 0, low: 0 };
    
    const distribution = { high: 0, medium: 0, low: 0 };
    
    agents.forEach(agent => {
      const energy = agent.energy || 0;
      if (energy > 0.7) distribution.high++;
      else if (energy > 0.4) distribution.medium++;
      else distribution.low++;
    });
    
    return distribution;
  }, [agents]);
  
  // Get energy level color
  const getEnergyLevelColor = (energy) => {
    if (energy > 0.7) return 'high-energy';
    if (energy > 0.4) return 'medium-energy';
    return 'low-energy';
  };
  
  // Format number for display
  const formatNumber = (num, decimals = 2) => {
    if (typeof num !== 'number') return '0.00';
    return num.toFixed(decimals);
  };
  
  return (
    <div className="agent-metrics">
      <h3>System Metrics</h3>
      
      {/* Core Metrics Grid */}
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-label">Total Agents</div>
          <div className="metric-value">{liveMetrics.totalAgents}</div>
        </div>
        
        <div className="metric-card">
          <div className="metric-label">Active Memes</div>
          <div className="metric-value">{liveMetrics.totalActiveMemes}</div>
        </div>
        
        <div className="metric-card">
          <div className="metric-label">Avg Energy</div>
          <div className="metric-value">{formatNumber(liveMetrics.averageEnergy)}</div>
        </div>
        
        <div className="metric-card">
          <div className="metric-label">Avg Health</div>
          <div className="metric-value">{formatNumber(liveMetrics.averageHealth)}</div>
        </div>
        
        <div className="metric-card">
          <div className="metric-label">Entanglements</div>
          <div className="metric-value">{liveMetrics.activeEntanglements}</div>
        </div>
        
        <div className="metric-card">
          <div className="metric-label">Current Step</div>
          <div className="metric-value">{currentStep}</div>
        </div>
      </div>
      
      {/* Energy Distribution */}
      <div className="control-group">
        <h4>Energy Distribution</h4>
        <div className="energy-distribution">
          <div className="distribution-bar">
            <div className="distribution-item high-energy" style={{
              width: `${agents.length > 0 ? (energyDistribution.high / agents.length) * 100 : 0}%`
            }}>
              <span>{energyDistribution.high}</span>
            </div>
            <div className="distribution-item medium-energy" style={{
              width: `${agents.length > 0 ? (energyDistribution.medium / agents.length) * 100 : 0}%`
            }}>
              <span>{energyDistribution.medium}</span>
            </div>
            <div className="distribution-item low-energy" style={{
              width: `${agents.length > 0 ? (energyDistribution.low / agents.length) * 100 : 0}%`
            }}>
              <span>{energyDistribution.low}</span>
            </div>
          </div>
          <div className="distribution-legend">
            <div><span className="legend-color high-energy"></span>High (>0.7)</div>
            <div><span className="legend-color medium-energy"></span>Medium (0.4-0.7)</div>
            <div><span className="legend-color low-energy"></span>Low (<0.4)</div>
          </div>
        </div>
      </div>
      
      {/* Agent List */}
      {agents.length > 0 && (
        <div className="control-group">
          <h4>Agent Status</h4>
          <div className="agent-list">
            {agents.slice(0, 10).map(agent => ( // Limit to first 10 for performance
              <div key={agent.id} className="agent-item">
                <div className="agent-info">
                  <div className="agent-id">{agent.id}</div>
                  <div className="agent-stats">
                    E:{formatNumber(agent.energy || 0)} | 
                    H:{formatNumber(agent.health || 1)} | 
                    M:{agent.active_memes || 0}
                  </div>
                </div>
                <div className={`agent-indicator ${getEnergyLevelColor(agent.energy || 0)}`}></div>
              </div>
            ))}
            
            {agents.length > 10 && (
              <div className="agent-item">
                <div className="agent-info">
                  <div className="agent-id">... and {agents.length - 10} more agents</div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      
      {/* Recent Activity */}
      <div className="control-group">
        <h4>Recent Activity</h4>
        
        {/* Recent Entanglements */}
        {entanglements.length > 0 && (
          <div className="activity-section">
            <div className="activity-header">Latest Entanglements</div>
            {entanglements.slice(-3).map((entanglement, index) => (
              <div key={index} className="activity-item">
                <span className="activity-time">
                  {new Date(entanglement.timestamp * 1000).toLocaleTimeString()}
                </span>
                <span className="activity-desc">
                  {entanglement.source} ⟷ {entanglement.target} 
                  ({formatNumber(entanglement.strength)})
                </span>
              </div>
            ))}
          </div>
        )}
        
        {/* Recent Meme Events */}
        {memeEvents.length > 0 && (
          <div className="activity-section">
            <div className="activity-header">Latest Meme Events</div>
            {memeEvents.slice(-3).map((event, index) => (
              <div key={index} className="activity-item">
                <span className="activity-time">
                  {new Date(event.timestamp * 1000).toLocaleTimeString()}
                </span>
                <span className="activity-desc">
                  {event.type}: {event.agent_id || event.source_agent}
                  {event.meme_id && ` (${event.meme_id.substring(0, 8)}...)`}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default AgentMetrics;