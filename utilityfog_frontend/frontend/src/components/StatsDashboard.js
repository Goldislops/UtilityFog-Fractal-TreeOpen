import React from 'react';
import { useSimBridge } from '../contexts/SimBridgeContext';

const StatsDashboard = () => {
  const {
    stats,
    currentStep,
    totalSteps,
    progress,
    entanglements,
    memeSpreads,
    currentAgents,
    recentEvents
  } = useSimBridge();
  
  return (
    <div className="stats-dashboard bg-gray-900 p-4 rounded-lg border border-gray-600">
      <h2 className="text-xl font-bold text-white mb-4">Statistics</h2>
      
      {/* Progress */}
      <div className="mb-6">
        <div className="flex justify-between text-sm text-gray-300 mb-1">
          <span>Progress</span>
          <span>{currentStep}/{totalSteps}</span>
        </div>
        <div className="w-full bg-gray-700 rounded-full h-2">
          <div 
            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          ></div>
        </div>
      </div>
      
      {/* Core Statistics */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="metric-card bg-gray-800 p-3 rounded">
          <div className="text-xs text-gray-400 uppercase">Active Agents</div>
          <div className="text-2xl font-bold text-white">{stats.active_agents || currentAgents.length}</div>
        </div>
        
        <div className="metric-card bg-gray-800 p-3 rounded">
          <div className="text-xs text-gray-400 uppercase">Total Memes</div>
          <div className="text-2xl font-bold text-green-400">{stats.total_memes || 0}</div>
        </div>
        
        <div className="metric-card bg-gray-800 p-3 rounded">
          <div className="text-xs text-gray-400 uppercase">Avg Energy</div>
          <div className="text-2xl font-bold text-blue-400">{(stats.average_energy || 0).toFixed(2)}</div>
        </div>
        
        <div className="metric-card bg-gray-800 p-3 rounded">
          <div className="text-xs text-gray-400 uppercase">Avg Health</div>
          <div className="text-2xl font-bold text-purple-400">{(stats.average_health || 0).toFixed(2)}</div>
        </div>
      </div>
      
      {/* Event Counters */}
      <div className="mb-6">
        <h3 className="text-lg font-semibold text-white mb-3">Real-time Events</h3>
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-gray-300">Active Entanglements</span>
            <span className="text-purple-400 font-bold">{entanglements.length}</span>
          </div>
          
          <div className="flex justify-between text-sm">
            <span className="text-gray-300">Meme Spreads</span>
            <span className="text-orange-400 font-bold">{memeSpreads.length}</span>
          </div>
          
          <div className="flex justify-between text-sm">
            <span className="text-gray-300">Total Events</span>
            <span className="text-cyan-400 font-bold">{recentEvents.length}</span>
          </div>
        </div>
      </div>
      
      {/* Recent Event Feed */}
      <div>
        <h3 className="text-lg font-semibold text-white mb-3">Recent Events</h3>
        <div className="space-y-1 max-h-40 overflow-y-auto">
          {recentEvents.slice(0, 8).map((event) => (
            <div key={event.id} className="text-xs p-2 bg-gray-800 rounded flex justify-between">
              <span className={`font-bold ${
                event.type === 'ENTANGLEMENT' ? 'text-purple-400' :
                event.type === 'MEME_SPREAD' ? 'text-orange-400' : 'text-cyan-400'
              }`}>
                {event.type}
              </span>
              <span className="text-gray-400">
                {event.type === 'ENTANGLEMENT' && `${event.data.source} ⟷ ${event.data.target}`}
                {event.type === 'MEME_SPREAD' && `${event.data.source} → ${event.data.targets?.length || 0} agents`}
              </span>
              <span className="text-gray-500 text-xs">
                {Math.floor((Date.now() - event.timestamp) / 1000)}s ago
              </span>
            </div>
          ))}
          
          {recentEvents.length === 0 && (
            <div className="text-gray-500 text-sm text-center py-4">
              No events yet
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default StatsDashboard;