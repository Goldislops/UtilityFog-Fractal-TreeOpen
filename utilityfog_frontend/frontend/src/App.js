import React from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid, Stats } from '@react-three/drei';
import { Suspense } from 'react';

import { SimulationProvider } from './contexts/SimulationContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import Dashboard from './components/Dashboard';
import Network3D from './components/Network3D';
import MemeTimeline from './components/MemeTimeline';
import AgentMetrics from './components/AgentMetrics';
import StatusBar from './components/StatusBar';
import LoadingSpinner from './components/LoadingSpinner';

import './App.css';

function App() {
  return (
    <div className="app">
      <WebSocketProvider>
        <SimulationProvider>
          {/* Main 3D Visualization */}
          <div className="main-container">
            <div className="canvas-container">
              <Canvas
                camera={{ position: [100, 100, 100], fov: 60 }}
                style={{ background: 'radial-gradient(circle, #1a1a2e, #0f0f23)' }}
              >
                <Suspense fallback={null}>
                  {/* Lighting */}
                  <ambientLight intensity={0.4} />
                  <pointLight position={[100, 100, 100]} intensity={1} />
                  <pointLight position={[-100, -100, -100]} intensity={0.5} />
                  
                  {/* Controls */}
                  <OrbitControls
                    enablePan={true}
                    enableZoom={true}
                    enableRotate={true}
                    minDistance={10}
                    maxDistance={500}
                  />
                  
                  {/* Grid for reference */}
                  <Grid
                    args={[200, 200]}
                    cellSize={10}
                    cellThickness={0.5}
                    cellColor="#333"
                    sectionSize={50}
                    sectionThickness={1}
                    sectionColor="#555"
                    fadeDistance={300}
                    fadeStrength={1}
                    followCamera={false}
                    infiniteGrid={false}
                  />
                  
                  {/* Main 3D Network Visualization */}
                  <Network3D />
                  
                  {/* Performance stats (dev mode) */}
                  {process.env.NODE_ENV === 'development' && <Stats />}
                </Suspense>
              </Canvas>
              
              {/* Loading overlay */}
              <LoadingSpinner />
            </div>

            {/* Side Panels */}
            <div className="side-panels">
              {/* Control Dashboard */}
              <div className="panel dashboard-panel">
                <Dashboard />
              </div>

              {/* Agent Metrics */}
              <div className="panel metrics-panel">
                <AgentMetrics />
              </div>
            </div>
          </div>

          {/* Bottom Panel - Timeline */}
          <div className="bottom-panel">
            <MemeTimeline />
          </div>

          {/* Status Bar */}
          <StatusBar />
        </SimulationProvider>
      </WebSocketProvider>
    </div>
  );
}

export default App;